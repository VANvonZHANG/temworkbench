import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, RLock

from .device import Frame, SimulatorProcess
from .models import Acquire, DeviceState, Exposure, Job, JobRef, Request, Role, SetMagnification
from .storage import Events, preview_jpeg, published_dataset, save_dataset

LOGGER = logging.getLogger(__name__)
APPROVAL_SECONDS = 45
OPERATOR_LEASE_SECONDS = 15
ACTIVE = ("pending_approval", "queued", "running")


class Rejected(RuntimeError):
    pass


class UnknownJob(LookupError):
    pass


class Workbench:
    def __init__(self, root: Path, device: SimulatorProcess):
        self.device = device
        self.state = device.initial_state
        self.datasets = root / "datasets"
        self.events = Events(root / "events.sqlite3")
        self.lock = RLock()
        self.device_queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix="device")
        self.storage_queue = ThreadPoolExecutor(max_workers=1, thread_name_prefix="storage")
        self.preview_slot = BoundedSemaphore()
        self.operator_until = 0.0
        self.stopped = False
        for job in self.events.latest():
            if job.status in ACTIVE:
                dataset = (
                    published_dataset(self.datasets, job)
                    if isinstance(job.command, Acquire)
                    else None
                )
                if dataset:
                    self._change(job, "succeeded", dataset=dataset, error=None)
                else:
                    self._change(job, "failed", error="Service restarted before job completion")

    def _change(self, job: Job, status: str, **fields) -> Job:
        updated = job.model_copy(update={"status": status, **fields})
        self.events.append(status, updated)
        return updated

    def operator_present(self) -> None:
        with self.lock:
            self.operator_until = time.monotonic() + OPERATOR_LEASE_SECONDS

    def get_state(self) -> dict:
        with self.lock:
            return {
                "device": self.state.model_dump(mode="json"),
                "stopped": self.stopped,
                "device_connected": self.device.process.poll() is None,
            }

    def _expire(self, job: Job) -> Job:
        if job.status == "pending_approval" and (
            time.time() - job.submitted_at >= APPROVAL_SECONDS
            or time.monotonic() >= self.operator_until
        ):
            return self._change(job, "rejected", error="Operator approval expired")
        return job

    def get_job(self, ref: JobRef) -> Job:
        with self.lock:
            job = self.events.get(ref)
            if job is None:
                raise UnknownJob(ref.command_id)
            return self._expire(job)

    def list_jobs(self, session_id: str) -> list[Job]:
        with self.lock:
            return [self._expire(job) for job in self.events.latest(session_id)]

    def pending(self) -> list[Job]:
        with self.lock:
            self.expire_approvals()
            self.operator_present()
            return [job for job in self.events.latest() if job.status == "pending_approval"]

    def expire_approvals(self) -> None:
        with self.lock:
            for job in self.events.latest():
                self._expire(job)

    def submit(self, request: Request, actor: Role) -> Job:
        with self.lock:
            ref = JobRef(session_id=request.session_id, command_id=request.command_id)
            previous = self.events.get(ref)
            if previous is not None:
                if previous.command != request.command or previous.actor != actor:
                    raise Rejected("Command ID already belongs to a different command")
                return self._expire(previous)
            command = request.command
            job = Job(
                **ref.model_dump(),
                command=command,
                actor=actor,
                status="queued",
                submitted_at=time.time(),
            )
            if self.stopped:
                return self._change(job, "rejected", error="Workbench is stopped")
            if (
                isinstance(command, SetMagnification)
                and command.value not in self.state.magnifications
            ):
                return self._change(
                    job, "rejected", error="Magnification is unavailable in this mode"
                )
            if sum(self._expire(item).status in ACTIVE for item in self.events.latest()) >= 32:
                raise Rejected("Command queue is full")
            if actor == "agent" and not isinstance(command, Acquire):
                if time.monotonic() >= self.operator_until:
                    return self._change(job, "rejected", error="No operator is available")
                return self._change(job, "pending_approval")
            self.events.append("queued", job)
            self.device_queue.submit(self._run, job)
            return job

    def approve(self, ref: JobRef, allow: bool) -> Job:
        with self.lock:
            job = self.get_job(ref)
            if job.status != "pending_approval":
                return job
            if not allow:
                return self._change(job, "rejected", error="Operator denied the command")
            job = job.model_copy(update={"status": "queued"})
            self.events.append("operator_approved", job)
            self.device_queue.submit(self._run, job)
            return job

    def _failed(self, job: Job, error: Exception) -> None:
        with self.lock:
            self._change(job, "failed", error=str(error))

    def _run(self, job: Job) -> None:
        with self.lock:
            if self.stopped:
                return
            job = self._change(job, "running")
        try:
            command = job.command
            if isinstance(command, Acquire):
                frame = self.device.capture(command)
                self.storage_queue.submit(self._save, job, frame, command)
            else:
                state = DeviceState.model_validate(self.device.request(command.model_dump()))
                with self.lock:
                    self.state = state
                    self._change(job, "succeeded")
        except Exception as error:
            LOGGER.exception("Command %s failed", job.command_id)
            self._failed(job, error)

    def _save(self, job: Job, frame: Frame, exposure: Exposure) -> None:
        try:
            dataset = save_dataset(self.datasets, job, frame, exposure)
            with self.lock:
                self._change(job, "succeeded", dataset=dataset)
        except Exception as error:
            LOGGER.exception("Command %s failed", job.command_id)
            self._failed(job, error)

    def _preview(self, exposure: Exposure) -> bytes:
        with self.lock:
            if self.stopped:
                raise Rejected("Workbench is stopped")
        return preview_jpeg(self.device.capture(exposure))

    def preview(self, exposure: Exposure) -> bytes:
        if not self.preview_slot.acquire(blocking=False):
            raise Rejected("A preview frame is already queued")
        future = self.device_queue.submit(self._preview, exposure)
        future.add_done_callback(lambda _: self.preview_slot.release())
        return future.result()

    def stop(self) -> DeviceState:
        with self.lock:
            if not self.stopped:
                self.stopped = True
                self.events.append("operator_stop")
                for job in self.events.latest():
                    if job.status in ("queued", "pending_approval"):
                        self._change(job, "canceled", error="Operator stopped the workbench")
                self.stop_result: Future[DeviceState] = self.device_queue.submit(self._blank)
        return self.stop_result.result()

    def _blank(self) -> DeviceState:
        state = DeviceState.model_validate(self.device.request({"kind": "stop"}))
        with self.lock:
            self.state = state
            self.events.append("beam_blanked")
        return state

    def close(self) -> None:
        self.device_queue.shutdown()
        self.storage_queue.shutdown()
        self.events.db.close()
