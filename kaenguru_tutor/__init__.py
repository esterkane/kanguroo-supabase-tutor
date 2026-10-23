"""Public host API of the Känguru tutor (T3.1, AuDHS ADR 0021 draft). Hosts import only from here.

    from kaenguru_tutor import HostConfig, build_service, router
    app.state.tutor = build_service(HostConfig(...), hooks=MyHooks())   # open() in lifespan, close() on exit
    app.include_router(router, prefix="/api/kaenguru")

Install as an editable path dependency (prompts, labs and scripts are read from the repository).
"""
from backend.tutor.host import HostConfig, HostHooks, HostRefusal, HostVerifier, ModelCall, build_service
from backend.tutor.router import router

__all__ = ["HostConfig", "HostHooks", "HostRefusal", "HostVerifier", "ModelCall", "build_service", "router"]
