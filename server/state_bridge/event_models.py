"""Pydantic schemas for outbound bridge event payloads.

The bridge publishes events on the bus and over /state/events (SSE) and
the /ws WebSocket. Every payload that crosses that boundary is now
validated through one of the models below before being serialized.

Mirror of `client/Interface/src/types/bridgeProtocol.ts` — when a field
is added to one side, mirror it on the other.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _EventDataBase(BaseModel):
    """Shared base: forbid extra fields so a typo in a publish site
    surfaces at validation time instead of as a silent wire drift."""

    model_config = ConfigDict(extra="forbid")


# ── Movement / state events ──────────────────────────────────────────


class FenUpdateData(_EventDataBase):
    fen: str
    source: str
    side_to_move: str
    result: str
    is_check: bool


class CvCaptureData(_EventDataBase):
    fen: str
    source: str
    side_to_move: str
    result: str
    is_check: bool


class MoveMadeData(_EventDataBase):
    from_: str = Field(alias="from")
    to: str
    source: str
    piece: str | None = None
    fen: str | None = None
    result: str | None = None
    is_check: bool | None = None
    score: int | float | None = None
    from_r: int | None = None
    from_c: int | None = None
    to_r: int | None = None
    to_c: int | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PieceSelectedData(_EventDataBase):
    square: str
    targets: list[str] = []


class BestMoveData(_EventDataBase):
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GameResetData(_EventDataBase):
    """GAME_RESET carries no payload."""


# ── LED ──────────────────────────────────────────────────────────────


class LedCommandData(_EventDataBase):
    command: str


# ── CV pipeline ──────────────────────────────────────────────────────


class CvCaptureRequestedData(_EventDataBase):
    source: str
    endpoint: str
    cv_service_url: str


class CvCaptureResultData(_EventDataBase):
    status: str
    fen: str | None = None
    issues: list[str] = []
    source: str = "cv"
    capture_id: str | int | None = None
    captured_at: str | None = None
    image_path: str | None = None
    image_mime: str | None = None

    @field_validator("captured_at", mode="before")
    @classmethod
    def _normalize_captured_at(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        return str(value)


class CvValidationErrorData(_EventDataBase):
    source: str
    cv_fen: str
    current_fen: str
    reason: str


# ── Kibo ─────────────────────────────────────────────────────────────


class KiboTriggerData(_EventDataBase):
    trigger: str
    duration: float | None = None


# ── State sync (initial SSE frame) ───────────────────────────────────
# state.to_dict() returns an open shape that includes engine bookkeeping
# (event_seq, move_count, …); validate the well-known keys but allow
# extras so future state additions don't require a schema bump.


class StateSyncData(BaseModel):
    model_config = ConfigDict(extra="allow")

    fen: str
    side_to_move: str
    game_result: str
    is_check: bool


def model_to_event_data(payload: BaseModel) -> dict[str, Any]:
    """Serialize a model into the on-wire dict.

    `by_alias=True` so the `from_` → `from` rename round-trips correctly.
    `exclude_none=True` matches the current wire format which omits null
    optional fields rather than emitting `null`.
    """
    return payload.model_dump(by_alias=True, exclude_none=True)
