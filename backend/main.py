"""Standalone entrypoint. The AuDHS Tutor mounts backend.tutor.router instead."""
from fastapi import FastAPI

app = FastAPI(title="Känguru Tutor")

# from backend.tutor.router import router as tutor_router  # T1.8
# app.include_router(tutor_router, prefix="/tutor")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
