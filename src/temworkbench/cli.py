import argparse
import os
import secrets
from pathlib import Path

import uvicorn

from .api import build_app


def main():
    parser = argparse.ArgumentParser(description="Run the Instamatic TEM simulator workbench")
    parser.add_argument("--data", type=Path, default=Path("run"))
    parser.add_argument("--port", type=int, default=8765)
    default_device = Path(".venv-device") / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    parser.add_argument("--device-python", type=Path, default=default_device)
    args = parser.parse_args()
    if not args.device_python.is_file():
        parser.error(f"Simulator Python not found: {args.device_python}. Install the device group.")
    operator = os.environ.get("TEMWORKBENCH_OPERATOR_TOKEN")
    agent = os.environ.get("TEMWORKBENCH_AGENT_TOKEN")
    if not operator:
        operator = secrets.token_urlsafe(24)
        print(f"Operator token: {operator}", flush=True)
    if not agent:
        agent = secrets.token_urlsafe(24)
        print(f"Agent token: {agent}", flush=True)
    app = build_app(args.data.resolve(), args.device_python.absolute(), operator, agent)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
