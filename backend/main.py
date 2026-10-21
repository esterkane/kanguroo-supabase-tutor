"""Standalone entrypoint. The AuDHS Tutor mounts backend.tutor.router instead."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.tutor.router import router as tutor_router
from backend.tutor.service import TutorService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    svc = TutorService.from_env()  # reads .env.local (make env) + .env, see Makefile `dev`
    await svc.open()
    app.state.tutor = svc
    try:
        yield
    finally:
        await svc.close()


app = FastAPI(title="Känguru Tutor", lifespan=lifespan)
app.include_router(tutor_router, prefix="/tutor")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
