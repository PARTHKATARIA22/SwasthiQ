"""
Root entrypoint for deployment environments (e.g. Vercel, Render).
Re-exports the FastAPI app from backend.app.
"""
from backend.app import app

__all__ = ["app"]
