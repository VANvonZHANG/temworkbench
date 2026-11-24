import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from filelock import FileLock
from starlette.concurrency import run_in_threadpool

from .device import DeviceError, SimulatorProcess
from .models import (
    Job,
    JobRef,
    Request,
    Role,
    SessionId,
)
from .storage import dataset_paths
from .workbench import Rejected, UnknownJob, Workbench

LOGGER = logging.getLogger(__name__)


def build_app(root: Path, device_python: Path, operator_token: str, agent_token: str) -> FastAPI:
    if not operator_token or not agent_token or operator_token == agent_token:
        raise ValueError("Operator and agent require distinct, nonempty tokens")

    workbench: Workbench

    def identify(authorization: str) -> Role | None:
        token = authorization.encode()
        if compare_digest(token, f"Bearer {operator_token}".encode()):
            return "operator"
        if compare_digest(token, f"Bearer {agent_token}".encode()):
            return "agent"
        return None

    async def expire_approvals():
        while True:
            await asyncio.sleep(1)
            await run_in_threadpool(workbench.expire_approvals)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal workbench
        root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(root / ".workbench.lock"), timeout=0):
            device = SimulatorProcess(device_python)
            active: Workbench | None = None
            try:
                active = workbench = Workbench(root, device)
                async with asyncio.TaskGroup() as tasks:
                    expiry = tasks.create_task(expire_approvals())
                    try:
                        yield
                    finally:
                        expiry.cancel()
            finally:
                try:
                    if active is not None:
                        active.close()
                finally:
                    device.close()

    app = FastAPI(title="TEM Workbench", lifespan=lifespan, docs_url=None, redoc_url=None)

    def role(authorization: str = Header(default="")) -> Role:
        actor = identify(authorization)
        if actor is None:
            raise HTTPException(
                401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )
        return actor

    Authenticated = Annotated[Role, Depends(role)]

    def require_operator(actor: Authenticated) -> None:
        if actor != "operator":
            raise HTTPException(403, "Operator token required")

    @app.exception_handler(Rejected)
    async def rejected(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(UnknownJob)
    async def unknown(_request, _error):
        return JSONResponse({"detail": "Job not found"}, status_code=404)

    @app.exception_handler(DeviceError)
    async def offline(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.get("/api/state")
    def state(session_id: SessionId, _actor: Authenticated) -> dict:
        return {"session_id": session_id, **workbench.get_state()}

    @app.post("/api/commands", status_code=202)
    def submit(request: Request, actor: Authenticated) -> Job:
        return workbench.submit(request, actor)

    @app.get("/api/jobs/{session_id}/{command_id}")
    def job(session_id: SessionId, command_id: UUID, _actor: Authenticated) -> Job:
        return workbench.get_job(JobRef(session_id=session_id, command_id=command_id))

    @app.get("/api/jobs/{session_id}/{command_id}/files/{format}")
    def download(session_id: SessionId, command_id: UUID, format: str, _actor: Authenticated):
        ref = JobRef(session_id=session_id, command_id=command_id)
        result = workbench.get_job(ref)
        hspy, tiff = dataset_paths(workbench.datasets, ref)
        paths = {"hspy": hspy, "tiff": tiff}
        if result.status != "succeeded" or result.dataset is None or format not in paths:
            raise HTTPException(404, "Acquisition file not found")
        path = paths[format]
        if not path.is_file():
            raise HTTPException(404, "Acquisition file not found")
        return FileResponse(path, filename=f"{command_id}.{format}")

    @app.get("/api/operator/approvals", dependencies=[Depends(require_operator)])
    def approvals() -> list[Job]:
        return workbench.pending()

    @app.post(
        "/api/operator/approvals/{session_id}/{command_id}",
        dependencies=[Depends(require_operator)],
    )
    def decide(session_id: SessionId, command_id: UUID, allow: bool) -> Job:
        return workbench.approve(JobRef(session_id=session_id, command_id=command_id), allow)

    @app.post("/api/operator/stop", dependencies=[Depends(require_operator)])
    def stop():
        return workbench.stop()

    return app
