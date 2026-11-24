import io
import sqlite3
import tempfile
import time
from pathlib import Path

import hyperspy.api as hs
import numpy as np
import tifffile
from PIL import Image

from .device import Frame
from .models import Dataset, Exposure, Job, JobRef


class Events:
    def __init__(self, filename: Path):
        self.db = sqlite3.connect(filename, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY,
                at REAL NOT NULL,
                event TEXT NOT NULL,
                session_id TEXT,
                command_id TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS events_job
            ON events(session_id, command_id, sequence);
        """)

    def append(self, event: str, job: Job | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO events(at, event, session_id, command_id, detail) VALUES(?,?,?,?,?)",
                (
                    time.time(),
                    event,
                    job.session_id if job else None,
                    str(job.command_id) if job else None,
                    job.model_dump_json() if job else None,
                ),
            )

    def get(self, ref: JobRef) -> Job | None:
        row = self.db.execute(
            """SELECT detail FROM events WHERE session_id = ? AND command_id = ?
            ORDER BY sequence DESC LIMIT 1""",
            (ref.session_id, str(ref.command_id)),
        ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def latest(self, session_id: str | None = None) -> list[Job]:
        rows = self.db.execute(
            """SELECT detail FROM events WHERE sequence IN (
                SELECT MAX(sequence) FROM events
                WHERE command_id IS NOT NULL AND (? IS NULL OR session_id = ?)
                GROUP BY session_id, command_id
            ) ORDER BY sequence DESC""",
            (session_id, session_id),
        )
        return [Job.model_validate_json(row[0]) for row in rows]


def dataset_paths(root: Path, ref: JobRef) -> tuple[Path, Path]:
    directory = root / f"session-{ref.session_id}" / str(ref.command_id)
    return directory / "image.hspy", directory / "image.tiff"


def published_dataset(root: Path, ref: JobRef) -> Dataset | None:
    hspy, tiff = dataset_paths(root, ref)
    if hspy.is_file() and tiff.is_file():
        return Dataset(hspy=hspy.as_posix(), tiff=tiff.as_posix())
    return None


def save_dataset(root: Path, ref: JobRef, frame: Frame, exposure: Exposure) -> Dataset:
    hspy, tiff = dataset_paths(root, ref)
    hspy.parent.parent.mkdir(parents=True, exist_ok=True)
    state = frame.state
    signal = hs.signals.Signal2D(frame.pixels)
    if state.pixel_size_nm is not None:
        for axis, name in zip(signal.axes_manager.signal_axes, ("x", "y"), strict=True):
            axis.name = name
            axis.scale = state.pixel_size_nm * exposure.binning
            axis.units = "nm"
    signal.metadata.add_dictionary(
        {
            "General": {"title": f"TEM {ref.command_id}"},
            "Acquisition_instrument": {
                "TEM": {
                    "microscope": state.microscope,
                    "beam_energy": state.beam_energy_kev,
                    "magnification": state.magnification,
                    "Stage": {
                        "x": state.stage.x_nm / 1000,
                        "y": state.stage.y_nm / 1000,
                        "z": state.stage_z_nm / 1000,
                        "tilt_alpha": state.tilt_alpha_deg,
                    },
                    "Detector": {
                        "Camera": {
                            "name": state.camera,
                            "exposure": exposure.exposure_s,
                            "binning": exposure.binning,
                        }
                    },
                },
            },
        }
    )
    signal.original_metadata.add_dictionary(
        {
            "instamatic": frame.header,
            "state_snapshot": state.model_dump(mode="json"),
            "acquisition": ref.model_dump(mode="json"),
        }
    )
    with tempfile.TemporaryDirectory(prefix=".capture-", dir=hspy.parent.parent) as staging:
        stage = Path(staging)
        signal.save(stage / hspy.name, overwrite=True)
        tifffile.imwrite(
            stage / tiff.name,
            frame.pixels,
            photometric="minisblack",
            metadata={"ImageComment": frame.header["ImageComment"]},
        )
        stage.rename(hspy.parent)
    return Dataset(hspy=hspy.as_posix(), tiff=tiff.as_posix())


def preview_jpeg(frame: Frame) -> bytes:
    buffer = io.BytesIO()
    pixels = np.clip(frame.pixels, 0, 255).astype(np.uint8)
    Image.fromarray(pixels).save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()
