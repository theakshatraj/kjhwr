"""Vercel entrypoint for the Wind Forecast Decision Portal.

Vercel's Python runtime imports this module and looks for a module-level ASGI
``app``. The real application lives in ``backend/app``; this file exists only to
put that package on ``sys.path`` and re-export the app, so the deployed function
and a local ``uvicorn``/pytest run serve exactly the same code and the same
``/api/*`` routes. No behaviour is duplicated here.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: ``api/index.py`` -> ``parents[1]`` is the repository root. Resolved from
#: ``__file__`` rather than the process cwd: Vercel runs the function with the
#: project root as cwd, but a local import does not have to.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

__all__ = ["app"]
