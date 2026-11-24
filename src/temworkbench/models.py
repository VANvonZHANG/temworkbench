from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SessionId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Role = Literal["operator", "agent"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Exposure(Model):
    exposure_s: Annotated[float, Field(ge=0.01, le=2)] = 0.1
    binning: Literal[1, 2, 4] = 1


class StageTarget(Model):
    x_nm: Annotated[int, Field(ge=-100_000, le=100_000)]
    y_nm: Annotated[int, Field(ge=-100_000, le=100_000)]


class DeviceState(Model):
    microscope: str
    camera: str
    beam_energy_kev: float
    beam_blanked: bool
    magnification: int
    magnifications: tuple[int, ...]
    brightness: int
    defocus_ticks: int
    stage: StageTarget
    stage_z_nm: int
    tilt_alpha_deg: float
    mode: str
    pixel_size_nm: float | None


class Acquire(Exposure):
    kind: Literal["acquire_image"]


class SetMagnification(Model):
    kind: Literal["set_magnification"]
    value: Annotated[int, Field(gt=0)]


class SetBrightness(Model):
    kind: Literal["set_brightness"]
    value: Annotated[int, Field(ge=0, le=65535)]


class SetDefocus(Model):
    kind: Literal["set_defocus"]
    ticks: Annotated[int, Field(ge=-1000, le=1000)]


class MoveStage(StageTarget):
    kind: Literal["move_stage"]


Command = Annotated[
    Acquire | SetMagnification | SetBrightness | SetDefocus | MoveStage,
    Field(discriminator="kind"),
]


class Request(Model):
    session_id: SessionId
    command_id: UUID
    command: Command


class JobRef(Model):
    session_id: SessionId
    command_id: UUID


class Dataset(Model):
    hspy: str
    tiff: str


class Job(JobRef):
    command: Command
    actor: Role
    status: Literal[
        "pending_approval", "rejected", "queued", "running", "succeeded", "failed", "canceled"
    ]
    submitted_at: float
    dataset: Dataset | None = None
    error: str | None = None
