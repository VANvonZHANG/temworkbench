import base64
import json
import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .models import DeviceState, Exposure


@dataclass(frozen=True)
class Frame:
    pixels: NDArray[Any]
    header: dict[str, Any]
    state: DeviceState


class DeviceError(RuntimeError):
    pass


class SimulatorProcess:
    def __init__(self, python: Path):
        self.process = subprocess.Popen(
            [str(python), "-u", str(Path(__file__).with_name("simulator.py"))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.responses: queue.Queue[str] = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.initial_state = DeviceState.model_validate(self._receive(timeout=45))
        except Exception:
            self.close()
            raise

    def _read(self):
        stdout = self.process.stdout
        assert stdout is not None
        for line in stdout:
            self.responses.put(line)
        self.responses.put("")

    def _receive(self, timeout: float = 10) -> dict[str, Any]:
        try:
            line = self.responses.get(timeout=timeout)
        except queue.Empty as error:
            self.process.kill()
            raise DeviceError("Instamatic simulator timed out") from error
        if not line:
            raise DeviceError("Instamatic simulator exited")
        message = json.loads(line)
        if "error" in message:
            raise DeviceError(message["error"])
        return message["result"]

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        stdin = self.process.stdin
        assert stdin is not None
        try:
            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise DeviceError("Instamatic simulator is unavailable") from error
        return self._receive()

    def capture(self, exposure: Exposure) -> Frame:
        packet = self.request({**exposure.model_dump(), "kind": "acquire_image"})
        pixels = np.frombuffer(base64.b64decode(packet["pixels"]), dtype=packet["dtype"])
        return Frame(
            pixels.reshape(packet["shape"]),
            packet["header"],
            DeviceState.model_validate(packet["state"]),
        )

    def close(self):
        assert self.process.stdin is not None and self.process.stdout is not None
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join()
        self.process.stdout.close()
