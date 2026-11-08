"""The calling thread's frames in the backend's own code, as the pool guard
(app/utils/pool_guard.py) and the statement cap (app/utils/statement_cap.py)
tell where a test's checkout or statement came from."""

import sys
from pathlib import Path
from types import FrameType

# The app's code, from backend/.
APP = ("app/", "pilot_mcp/")

_ROOT = f"{Path(__file__).resolve().parents[2]}/"
_VENV = f"{_ROOT}.venv/"

# A frame: its file from backend/, its line and its function's qualname.
Frame = tuple[str, int, str]


def backend_stack() -> tuple[Frame, ...]:
    """The frames in the backend's own code of whatever called the calling
    function, outermost first."""
    frames: list[Frame] = []
    frame: FrameType | None = sys._getframe(2)
    while frame is not None:
        code = frame.f_code
        path = code.co_filename
        if path.startswith(_ROOT) and not path.startswith(_VENV):
            frames.append((path[len(_ROOT) :], frame.f_lineno, code.co_qualname))
        frame = frame.f_back
    frames.reverse()
    return tuple(frames)


def format_stack(stack: tuple[Frame, ...]) -> str:
    return "\n".join(f"    {path}:{line} in {name}" for path, line, name in stack)
