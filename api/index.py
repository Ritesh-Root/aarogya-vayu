import sys
import os
from pathlib import Path

# Add project root directory to sys.path so app module is discoverable
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.main import app as fastapi_app

class VercelPathRewriter:
    """
    ASGI middleware that restores the true URL path from Vercel's x-matched-path
    header or strips /api/index.py prefix before FastAPI router matches endpoints.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            matched_path = headers.get(b"x-matched-path")
            if matched_path:
                matched_str = matched_path.decode("latin1")
                if not matched_str.startswith("/api/index"):
                    scope["path"] = matched_str
            elif scope.get("path", "").startswith("/api/index.py"):
                rem = scope["path"][len("/api/index.py"):]
                scope["path"] = rem if rem else "/"
        await self.app(scope, receive, send)

app = VercelPathRewriter(fastapi_app)
