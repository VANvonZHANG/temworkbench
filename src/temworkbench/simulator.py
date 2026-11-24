"""Device subprocess. The control environment never imports Instamatic."""

import base64
import json
import logging
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from importlib.metadata import distribution
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger(__name__)


def prepare_config(root):
    source = Path(distribution("instamatic").locate_file("instamatic/config"))
    config = root / "config"
    config.mkdir()
    for name in ("microscope", "camera", "calibration"):
        target = config / name
        target.mkdir()
        shutil.copyfile(source / name / "simulate.yaml", target / "simulate.yaml")
    shutil.copyfile(source / "defaults.yaml", config / "defaults.yaml")
    (config / "settings.yaml").write_text(
        "microscope: simulate\ncamera: simulate\ncalibration: simulate\n"
        "simulate: true\nuse_tem_server: false\nuse_cam_server: false\n",
        encoding="utf-8",
    )
    os.environ["instamatic"] = str(root)


class Simulator:
    FOCUS_ZERO = 32768

    def __init__(self):
        from instamatic import config
        from instamatic.controller import initialize

        self.config = config
        self.ctrl = initialize(tem_name="simulate", cam_name="simulate", stream=False)
        self.ctrl.tem.setObjectiveLenseFine(self.FOCUS_ZERO)
        self.ctrl.beam.blank()
        self.ctrl.autoblank = True
        self.state = self.read_state()

    def read_state(self):
        ctrl = self.ctrl
        stage = ctrl.stage.get()
        mode = ctrl.mode.get()
        magnification = ctrl.magnification.value
        return {
            "microscope": "Instamatic simulate",
            "camera": ctrl.cam.name,
            "mode": mode,
            "beam_energy_kev": ctrl.high_tension / 1000,
            "beam_blanked": ctrl.beam.is_blanked,
            "magnification": magnification,
            "magnifications": self.config.microscope.ranges[mode],
            "brightness": ctrl.brightness.value,
            "defocus_ticks": ctrl.tem.getObjectiveLenseFine() - self.FOCUS_ZERO,
            "stage": {"x_nm": stage.x, "y_nm": stage.y},
            "stage_z_nm": stage.z,
            "tilt_alpha_deg": stage.a,
            "pixel_size_nm": self.config.calibration[mode]["pixelsize"].get(magnification),
        }

    def capture(self, exposure_s, binning):
        pixels, header = self.ctrl.get_image(exposure=exposure_s, binsize=binning, header_keys=())
        pixels = np.ascontiguousarray(pixels, dtype=np.uint8)
        return {
            "pixels": base64.b64encode(pixels).decode("ascii"),
            "shape": list(pixels.shape),
            "dtype": pixels.dtype.str,
            "header": header,
            "state": self.state,
        }

    def dispatch(self, request):
        kind = request["kind"]
        ctrl = self.ctrl
        if kind == "acquire_image":
            return self.capture(request["exposure_s"], request["binning"])
        if kind == "set_magnification":
            ctrl.magnification.value = request["value"]
        elif kind == "set_brightness":
            ctrl.brightness.value = request["value"]
        elif kind == "set_defocus":
            ctrl.tem.setObjectiveLenseFine(self.FOCUS_ZERO + request["ticks"])
        elif kind == "move_stage":
            ctrl.stage.set(x=request["x_nm"], y=request["y_nm"], wait=True)
        elif kind == "stop":
            ctrl.beam.blank()
        elif kind != "state":
            raise ValueError(f"Unknown device operation {kind}")
        self.state = self.read_state()
        return self.state


def main():
    with tempfile.TemporaryDirectory(prefix="temworkbench-sim-") as directory:
        prepare_config(Path(directory))
        protocol = sys.stdout
        with redirect_stdout(sys.stderr):
            simulator = Simulator()
            print(json.dumps({"result": simulator.state}), file=protocol, flush=True)
            for line in sys.stdin:
                try:
                    response = {"result": simulator.dispatch(json.loads(line))}
                    encoded = json.dumps(response, allow_nan=False)
                except Exception as error:
                    LOGGER.exception("Instamatic simulator command failed")
                    encoded = json.dumps({"error": str(error)})
                print(encoded, file=protocol, flush=True)


if __name__ == "__main__":
    main()
