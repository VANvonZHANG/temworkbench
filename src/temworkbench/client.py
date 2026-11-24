import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from .models import Acquire, Command, Job, Request


class Client:
    """Synchronous HTTP client for local scripts and Jupyter."""

    def __init__(self, token: str, session_id: str, url: str = "http://127.0.0.1:8765"):
        self.session_id = session_id
        self.http = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {token}"})

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.http.close()

    def state(self) -> dict:
        return (
            self.http.get("/api/state", params={"session_id": self.session_id})
            .raise_for_status()
            .json()
        )

    def submit(self, command: Command, *, command_id: UUID | None = None) -> Job:
        request = Request(
            session_id=self.session_id, command_id=command_id or uuid4(), command=command
        )
        response = self.http.post("/api/commands", json=request.model_dump(mode="json"))
        return Job.model_validate(response.raise_for_status().json())

    def acquire(
        self,
        *,
        exposure_s: float = 0.1,
        binning=1,
        comment: str = "",
        command_id: UUID | None = None,
    ) -> Job:
        return self.submit(
            Acquire(kind="acquire_image", exposure_s=exposure_s, binning=binning, comment=comment),
            command_id=command_id,
        )

    def wait(self, job: Job, *, timeout: float = 60) -> Job:
        deadline = time.monotonic() + timeout
        while job.status in ("queued", "running", "pending_approval"):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Job {job.command_id} is {job.status}")
            time.sleep(0.1)
            response = self.http.get(f"/api/jobs/{job.session_id}/{job.command_id}")
            job = Job.model_validate(response.raise_for_status().json())
        return job

    def load(self, job: Job):
        import hyperspy.api as hs

        if job.status != "succeeded" or job.dataset is None:
            raise ValueError(job.error or f"Job {job.command_id} has no dataset")
        return hs.load(Path(job.dataset.hspy))
