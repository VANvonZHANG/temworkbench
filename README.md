# TEM Workbench

English | [简体中文](README.zh-CN.md)

Preview and acquire transmission electron microscopy (TEM) images with Instamatic's `simulate` configuration. Each acquisition saves a HyperSpy `.hspy` file and a TIFF. The web console, Jupyter, and MCP share the same acquisition jobs and SQLite event log.

This release runs against a local simulator. The full acquisition workflow has been tested on Linux.

## Start the simulator

Run these commands from the project root. The control service and Instamatic use separate Python 3.11 environments.

```sh
uv sync --locked --python 3.11
UV_PROJECT_ENVIRONMENT=.venv-device uv sync --locked --only-group device --python 3.11
uv run --locked temworkbench
```

In PowerShell, run `$env:UV_PROJECT_ENVIRONMENT = ".venv-device"` before running the `uv sync` command with `--only-group device`. Then run `Remove-Item Env:UV_PROJECT_ENVIRONMENT` before starting the service.

Open `http://127.0.0.1:8765` and enter the operator token printed in the terminal. Use a session ID of up to 64 characters. Start with a lowercase letter or digit and use only lowercase letters, digits, underscores, and hyphens.

Click **开始预览** (Start preview) or **取图保存** (Acquire and save). You can add a note of up to 500 characters to an acquisition. The note is stored in `original_metadata.instamatic.ImageComment` in HyperSpy and in the TIFF's JSON image description. After capture, download either format from the console. The service saves both files under `run/datasets/session-<session-id>/<command-id>/` and keeps its event log at `run/events.sqlite3`.

Use `--data` to set the data folder, `--port` to set the port, or `--device-python` to specify the Python executable for the Instamatic environment. Set `TEMWORKBENCH_OPERATOR_TOKEN` and `TEMWORKBENCH_AGENT_TOKEN` to reuse tokens across restarts. The service binds to `127.0.0.1`.

## Acquire and load images in Jupyter

Run `uv sync --locked --group notebook`. Start JupyterLab with `uv run --locked --group notebook jupyter lab` and run the following in a Python 3.11 kernel.

```python
from getpass import getpass

from temworkbench.client import Client
from temworkbench.models import MoveStage

with Client(getpass("Operator token: "), "notebook") as tem:
    print(tem.state())
    job = tem.wait(tem.acquire(exposure_s=0.1, binning=2, comment="Grid A3"))
    signal = tem.load(job)
    print(signal.metadata.Acquisition_instrument.TEM)
    signal.plot()

    move = MoveStage(kind="move_stage", x_nm=1000, y_nm=-500)
    print(tem.wait(tem.submit(move)).status)
```

Read the available magnifications from `state()["device"]["magnifications"]`. Brightness uses the raw Instamatic scale. Defocus uses ticks relative to the simulated objective fine-focus zero. Stage moves use absolute X and Y coordinates in nanometers.

## Acquire images or request adjustments through MCP

Connect to `http://127.0.0.1:8765/mcp/` using the agent token as an HTTP bearer token. Use `get_state`, `acquire_image`, `get_job`, `list_jobs`, or `request_change`. Pass a `session_id` on every call. For acquisitions and adjustment requests, also pass a UUID as `command_id`. Reuse the same ID and parameters when retrying. `acquire_image` accepts an optional `comment` and returns a job. After the job succeeds, use `get_job` to find the output paths.

When an agent requests a microscope adjustment, a connected operator can approve or reject it in the web console. The service waits up to 45 seconds. When the console stops reporting that the operator is online, pending approvals remain available for up to 15 more seconds.

Click **停止并遮挡束斑** (Stop and blank beam) to cancel queued commands and pending approval requests. The service waits for the active device call to finish, then blanks the simulated beam. Restart the service to resume operation. The simulator starts in a fresh state, and published files and job records remain available.

## Run the integration tests

Install both environments, then run the tests from the project root.

```sh
uv run --locked pytest
```

Calibration, movement limits, and stop behavior still need validation on the target microscope and camera.

## License

TEM Workbench is licensed under the [GNU General Public License v3.0 only](LICENSE) (`GPL-3.0-only`).
