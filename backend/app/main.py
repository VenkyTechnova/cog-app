"""FastAPI application entry point.

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import create_all
from .routers import analytics, auth, candidates, compliance, delegation, outreach, public, requirements, settings, tasks, webhooks, workflows

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    stop = None
    if get_settings().embedded_worker:
        from .scheduler import start_embedded

        stop = start_embedded()
    yield
    if stop:
        stop.set()


app = FastAPI(
    title="Cognitech Recruiter Workflow Automation API",
    version="1.0.0",
    description="Standardize, so the conversation can be human. Automate the admin around the recruiter — never trust, judgment or compliance-sensitive explanations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, tasks, requirements, candidates, outreach, workflows, delegation, analytics, compliance, settings, public, webhooks):
    app.include_router(r.router)
app.include_router(candidates.dup_router)


@app.get("/api/health")
def health():
    return {"ok": True}


# Serve the built frontend (production image) when present.
_dist = Path(__file__).resolve().parent.parent / "static"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        f = _dist / full_path
        if full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
