import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastmcp import FastMCP
from filelock import FileLock
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .device import DeviceError, SimulatorProcess
from .models import (
    Acquire,
    CaptureComment,
    Exposure,
    Job,
    JobRef,
    MoveStage,
    Request,
    Role,
    SessionId,
    SetBrightness,
    SetDefocus,
    SetMagnification,
)
from .storage import dataset_paths
from .workbench import Rejected, UnknownJob, Workbench

LOGGER = logging.getLogger(__name__)


def build_app(root: Path, device_python: Path, operator_token: str, agent_token: str) -> FastAPI:
    if not operator_token or not agent_token or operator_token == agent_token:
        raise ValueError("Operator and agent require distinct, nonempty tokens")

    mcp = FastMCP("TEM Workbench simulator")
    workbench: Workbench

    def identify(authorization: str) -> Role | None:
        token = authorization.encode()
        if compare_digest(token, f"Bearer {operator_token}".encode()):
            return "operator"
        if compare_digest(token, f"Bearer {agent_token}".encode()):
            return "agent"
        return None

    @mcp.tool
    def get_state(session_id: SessionId) -> dict:
        """Read cached microscope and camera state for a session."""
        return {"session_id": session_id, **workbench.get_state()}

    @mcp.tool
    def get_job(session_id: SessionId, command_id: UUID) -> Job:
        """Read an acquisition or approval job by command ID."""
        return workbench.get_job(JobRef(session_id=session_id, command_id=command_id))

    @mcp.tool
    def list_jobs(session_id: SessionId) -> list[Job]:
        """List acquisition and approval jobs for a session."""
        return workbench.list_jobs(session_id)

    @mcp.tool
    def acquire_image(
        session_id: SessionId, command_id: UUID, exposure: Exposure, comment: CaptureComment = ""
    ) -> Job:
        """Queue a single simulated acquisition and return its job ID."""
        return workbench.submit(
            Request(
                session_id=session_id,
                command_id=command_id,
                command=Acquire(kind="acquire_image", comment=comment, **exposure.model_dump()),
            ),
            "agent",
        )

    @mcp.tool
    def request_change(
        session_id: SessionId,
        command_id: UUID,
        command: MoveStage | SetBrightness | SetDefocus | SetMagnification,
    ) -> Job:
        """Ask the active operator to approve a simulated microscope change."""
        return workbench.submit(
            Request(session_id=session_id, command_id=command_id, command=command), "agent"
        )

    mcp_http = mcp.http_app(path="/", stateless_http=True)

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
                async with mcp_http.lifespan(app), asyncio.TaskGroup() as tasks:
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

    @app.middleware("http")
    async def protect_mcp(request, call_next):
        if (request.url.path == "/mcp" or request.url.path.startswith("/mcp/")) and identify(
            request.headers.get("authorization", "")
        ) != "agent":
            return JSONResponse(
                {"detail": "Agent token required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

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

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(Path(__file__).with_name("index.html"))

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

    @app.websocket("/api/preview")
    async def preview(socket: WebSocket):
        await socket.accept()
        try:
            async with asyncio.timeout(5):
                authorization = await socket.receive_text()
            if identify(authorization) != "operator":
                await socket.close(code=1008)
                return
            while True:
                raw = await socket.receive_text()
                try:
                    exposure = Exposure.model_validate_json(raw)
                    frame = await run_in_threadpool(workbench.preview, exposure)
                except (Rejected, DeviceError, ValidationError) as error:
                    await socket.send_json({"error": str(error)})
                else:
                    await socket.send_bytes(frame)
        except WebSocketDisconnect:
            pass
        except TimeoutError:
            await socket.close(code=1008)
        except Exception:
            LOGGER.exception("Preview failed")
            await socket.close(code=1011)

    app.mount("/mcp", mcp_http)
    return app
