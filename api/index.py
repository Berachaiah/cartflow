"""
Vercel entrypoint.

Vercel's Python runtime looks for an ASGI callable named `app` in the function
file, so this module does nothing but put the repository root on `sys.path` (the
function runs from `api/`, and `app/` is one level up) and re-export the FastAPI
application unchanged.

Nothing else lives here on purpose: the app is the same object uvicorn serves
locally, so a route that works in dev cannot be missing in production because the
entrypoint built a different application.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402,F401
