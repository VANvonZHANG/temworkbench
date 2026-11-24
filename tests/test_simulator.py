import os
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import hyperspy.api as hs
import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient

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

        request = command("acquire_image", exposure_s=0.03, binning=2)
        with ThreadPoolExecutor(max_workers=2) as threads:
            responses = list(threads.map(lambda _: submit(client, request), range(2)))
        assert {response.status_code for response in responses} == {202}
        conflict = {**request, "command": {**request["command"], "binning": 4}}
        assert submit(client, conflict).status_code == 409
        job = finish(client, request)
        assert job["status"] == "succeeded", job
        signal = hs.load(job["dataset"]["hspy"])
        assert signal.data.shape == (258, 258)
        assert all(ax.units == "nm" for ax in signal.axes_manager.signal_axes)
        assert signal.axes_manager.signal_axes[0].scale == 2 * baseline["pixel_size_nm"]
        assert signal.metadata.Acquisition_instrument.TEM.beam_energy == baseline["beam_energy_kev"]
        assert signal.original_metadata.instamatic.ImageBinsize == 2
        assert signal.original_metadata.acquisition.command_id == request["command_id"]
        raw_tiff = (
            client.get(f"{path(request)}/files/tiff", headers=AGENT).raise_for_status().content
        )
        np.testing.assert_array_equal(tifffile.imread(BytesIO(raw_tiff)), signal.data)

    with TestClient(app) as restarted:
        assert submit(restarted, request).json() == job
