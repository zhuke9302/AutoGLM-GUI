"""AutoGLM-GUI Backend API Server (FastAPI + Socket.IO)."""

from dotenv import load_dotenv

# Load .env before importing the API module so that module-level and lifespan
# env reads (e.g. AUTOGLM_SERVER_URL) see values even when this module is
# imported directly (e.g. `uvicorn AutoGLM_GUI.server:app --reload`).
load_dotenv()

from socketio import ASGIApp

from AutoGLM_GUI.api import app as fastapi_app
from AutoGLM_GUI.socketio_server import sio

app = ASGIApp(
    other_asgi_app=fastapi_app, socketio_server=sio, socketio_path="/socket.io"
)

__all__ = ["app"]
