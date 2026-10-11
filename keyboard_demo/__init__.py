"""Educational keyboard-event demonstration package."""

from .domain import CaptureMode, RevealStage, SessionOrigin, SessionState, StopReason
from .session import SessionManager, SessionStartError

__all__ = [
    "CaptureMode",
    "RevealStage",
    "SessionManager",
    "SessionOrigin",
    "SessionStartError",
    "SessionState",
    "StopReason",
]
