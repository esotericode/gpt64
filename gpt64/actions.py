"""Bounded controller actions; no game-state access."""

from dataclasses import dataclass
import math

BUTTONS = ("A", "B", "Z", "Start", "L", "R", "C Up", "C Down", "C Left", "C Right")
MAX_SEGMENTS = 16
MAX_TOTAL_FRAMES = 240


@dataclass(frozen=True)
class Segment:
    frames: int
    x: float = 0.0
    y: float = 0.0
    buttons: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.frames) is not int or not 1 <= self.frames <= 120:
            raise ValueError("frames must be an integer from 1 to 120")
        for axis in (self.x, self.y):
            if isinstance(axis, bool) or not isinstance(axis, (int, float)):
                raise ValueError("stick axes must be numbers")
            if not math.isfinite(axis) or not -1 <= axis <= 1:
                raise ValueError("stick axes must be finite numbers from -1 to 1")
        if not isinstance(self.buttons, (list, tuple)) or any(b not in BUTTONS for b in self.buttons):
            raise ValueError(f"buttons must come from {BUTTONS}")
        if len(set(self.buttons)) != len(self.buttons):
            raise ValueError("duplicate buttons are not allowed")
        object.__setattr__(self, "buttons", tuple(self.buttons))

    def wire(self) -> str:
        mask = sum(1 << BUTTONS.index(button) for button in self.buttons)
        return f"{self.frames} {round(self.x * 80)} {round(self.y * 80)} {mask}"


def validate_sequence(segments):
    segments = tuple(segments)
    if not 1 <= len(segments) <= MAX_SEGMENTS or not all(isinstance(s, Segment) for s in segments):
        raise ValueError(f"a sequence needs 1–{MAX_SEGMENTS} Segment objects")
    if sum(s.frames for s in segments) > MAX_TOTAL_FRAMES:
        raise ValueError(f"a sequence cannot exceed {MAX_TOTAL_FRAMES} frames")
    return segments
