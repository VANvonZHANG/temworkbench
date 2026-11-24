import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Thread
from uuid import uuid4

import httpx
import hyperspy.api as hs
import numpy as np
import pytest
import tifffile
import uvicorn
from fastapi.testclient import TestClient
from fastmcp import Client as MCPClient

from temworkbench.api import build_app

OPERATOR = {"Authorization": "Bearer test-operator"}
AGENT = {"Authorization": "Bearer test-agent"}


@pytest.fixture
def app(tmp_path):
    executable = Path(".venv-device") / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert executable.is_file(), (
        "Install the simulator device group before running integration tests"
    )
    return build_app(tmp_path, executable.absolute(), "test-operator", "test-agent")


def command(kind, **params):
    return {"session_id": "test", "command_id": str(uuid4()), "command": {"kind": kind, **params}}


def submit(client, request, headers=AGENT):
    return client.post("/api/commands", json=request, headers=headers)


def path(request):
    return f"/api/jobs/{request['session_id']}/{request['command_id']}"


def state(client):
    return client.get("/api/state?session_id=test", headers=OPERATOR).raise_for_status().json()


def finish(client, request):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        job = client.get(path(request), headers=AGENT).raise_for_status().json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.1)
    pytest.fail(f"Job {request['command_id']} did not finish")


def test_preview_and_capture_survive_retry_and_restart(app):
    with TestClient(app) as client:
        baseline = state(client)["device"]
        with client.websocket_connect("/api/preview") as socket:
            socket.send_text(OPERATOR["Authorization"])
            socket.send_json({"exposure_s": 0.01, "binning": 4})
            assert socket.receive_bytes().startswith(b"\xff\xd8")
        assert not client.get("/api/state?session_id=test").is_success
        invalid = command("acquire_image", comment="invalid\0comment")
        assert submit(client, invalid).status_code == 422

        comment = "网格 A3，低倍定位"
        request = command("acquire_image", exposure_s=0.03, binning=2, comment=comment)
        with ThreadPoolExecutor(max_workers=2) as threads:
            responses = list(threads.map(lambda _: submit(client, request), range(2)))
        assert {response.status_code for response in responses} == {202}
        conflict = {**request, "command": {**request["command"], "comment": "另一条备注"}}
        assert submit(client, conflict).status_code == 409
        job = finish(client, request)
        assert job["status"] == "succeeded", job
        signal = hs.load(job["dataset"]["hspy"])
        assert signal.data.shape == (258, 258)
        assert all(ax.units == "nm" for ax in signal.axes_manager.signal_axes)
        assert signal.axes_manager.signal_axes[0].scale == 2 * baseline["pixel_size_nm"]
        assert signal.metadata.Acquisition_instrument.TEM.beam_energy == baseline["beam_energy_kev"]
        assert signal.original_metadata.instamatic.ImageBinsize == 2
        assert signal.original_metadata.instamatic.ImageComment == comment
        assert signal.original_metadata.acquisition.command_id == request["command_id"]
        raw_tiff = (
            client.get(f"{path(request)}/files/tiff", headers=AGENT).raise_for_status().content
        )
        with tifffile.TiffFile(BytesIO(raw_tiff)) as tiff:
            np.testing.assert_array_equal(tiff.asarray(), signal.data)
            assert json.loads(tiff.pages[0].description)["ImageComment"] == comment

    with TestClient(app) as restarted:
        assert submit(restarted, request).json() == job


def test_approval_controls_stop_and_limits(app):
    with TestClient(app) as client:
        baseline = state(client)["device"]
        set_brightness = command("set_brightness", value=23456)
        no_operator = submit(client, set_brightness).json()
        assert no_operator["status"] == "rejected"
        assert client.get("/api/operator/approvals", headers=OPERATOR).json() == []
        assert submit(client, set_brightness).json() == no_operator

        stage = command("move_stage", x_nm=1234, y_nm=-4567)
        assert submit(client, stage).json()["status"] == "pending_approval"
        assert state(client)["device"]["stage"] == baseline["stage"]
        decision = f"/api/operator/approvals/test/{stage['command_id']}?allow=true"
        assert client.post(decision, headers=AGENT).status_code == 403
        assert client.post(decision, headers=OPERATOR).json()["status"] == "queued"
        assert finish(client, stage)["status"] == "succeeded"
        assert state(client)["device"]["stage"] == {"x_nm": 1234, "y_nm": -4567}
        assert client.post(decision, headers=OPERATOR).json()["status"] == "succeeded"

        denied = command("set_brightness", value=23567)
        assert submit(client, denied).json()["status"] == "pending_approval"
        deny = f"/api/operator/approvals/test/{denied['command_id']}?allow=false"
        assert client.post(deny, headers=OPERATOR).json()["status"] == "rejected"
        assert state(client)["device"]["brightness"] == baseline["brightness"]

        adjustments = [
            ("set_brightness", {"value": 12000}, "brightness", 12000),
            ("set_defocus", {"ticks": -50}, "defocus_ticks", -50),
            (
                "set_magnification",
                {"value": baseline["magnifications"][0]},
                "magnification",
                baseline["magnifications"][0],
            ),
        ]
        for kind, params, field, expected in adjustments:
            request = command(kind, **params)
            assert submit(client, request, OPERATOR).status_code == 202
            assert finish(client, request)["status"] == "succeeded"
            assert state(client)["device"][field] == expected
        assert submit(client, command("move_stage", x_nm=100001, y_nm=0)).status_code == 422
        assert submit(client, command("acquire_image", exposure_s=3)).status_code == 422

        pending = command("set_defocus", ticks=15)
        assert submit(client, pending).json()["status"] == "pending_approval"
        capturing = command("acquire_image", exposure_s=1.5)
        assert submit(client, capturing, OPERATOR).status_code == 202
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            current = client.get(path(capturing), headers=OPERATOR).json()
            if current["status"] == "running":
                break
            time.sleep(0.02)
        else:
            pytest.fail("Capture did not start")
        queued = command("acquire_image")
        assert submit(client, queued, OPERATOR).json()["status"] == "queued"
        assert client.post("/api/operator/stop", headers=AGENT).status_code == 403
        assert client.post("/api/operator/stop", headers=OPERATOR).json()["beam_blanked"]
        assert state(client)["stopped"] is True
        assert finish(client, pending)["status"] == "canceled"
        assert finish(client, queued)["status"] == "canceled"
        assert finish(client, capturing)["status"] == "succeeded"
        assert submit(client, command("acquire_image"), OPERATOR).json()["status"] == "rejected"


def test_mcp_uses_same_session_and_jobs(app):
    async def tools(http, url):
        async with MCPClient(f"{url}/mcp/", auth="test-agent") as client:
            names = {tool.name for tool in await client.list_tools()}
            assert names == {"get_state", "acquire_image", "get_job", "list_jobs", "request_change"}
            status = await client.call_tool("get_state", {"session_id": "test"})
            assert status.data["device"]["camera"] == "simulate"

            denied = command("set_defocus", ticks=-50)
            result = await client.call_tool("request_change", denied)
            assert result.structured_content["status"] == "rejected"

            request = command("acquire_image")
            ref = {key: request[key] for key in ("session_id", "command_id")}
            args = {**ref, "exposure": {"exposure_s": 0.02, "binning": 4}}
            submitted = await client.call_tool("acquire_image", args)
            assert submitted.structured_content["command_id"] == request["command_id"]
            job = await asyncio.to_thread(finish, http, request)
            assert job["status"] == "succeeded", job
            assert (await client.call_tool("get_job", ref)).structured_content == job
            assert (await client.call_tool("acquire_image", args)).structured_content == job
            listed = await client.call_tool("list_jobs", {"session_id": "test"})
            assert {entry["command_id"] for entry in listed.structured_content["result"]} == {
                denied["command_id"],
                request["command_id"],
            }

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 40
            while thread.is_alive() and not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, "Uvicorn startup failed"
            with httpx.Client(base_url=url, trust_env=False) as http:
                assert http.post("/mcp/").status_code == 401
                asyncio.run(tools(http, url))
        finally:
            server.should_exit = True
            thread.join(timeout=15)


def test_interrupted_capture_is_not_replayed(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "TEMWORKBENCH_OPERATOR_TOKEN": "test-operator",
        "TEMWORKBENCH_AGENT_TOKEN": "test-agent",
    }
    args = [
        sys.executable,
        "-m",
        "temworkbench.cli",
        "--port",
        str(port),
        "--data",
        str(tmp_path),
    ]
    request = command("acquire_image", exposure_s=2)

    def wait_for_service(service, client):
        deadline = time.monotonic() + 30
        while service.poll() is None and time.monotonic() < deadline:
            try:
                if client.get("/").is_success:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(0.05)
        pytest.fail("The workbench failed to start")

    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
        with subprocess.Popen(args, env=env) as service:
            try:
                wait_for_service(service, client)
                assert submit(client, request).status_code == 202
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if client.get(path(request), headers=AGENT).json()["status"] == "running":
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("Capture did not enter the running state")
            finally:
                service.kill()

        with subprocess.Popen(args, env=env) as service:
            try:
                wait_for_service(service, client)
                recovered = finish(client, request)
                assert recovered["status"] == "failed"
                assert recovered["dataset"] is None
                assert submit(client, request).json() == recovered
                assert not list(tmp_path.glob("datasets/**/image.*"))
            finally:
                service.terminate()
