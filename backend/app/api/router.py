from fastapi import APIRouter, Depends

from app.api.deps import require_auth
from app.api.routes import auth, domains, events, investigations, nodes, settings, system

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)

_protected = [Depends(require_auth)]
api_router.include_router(domains.router, dependencies=_protected)
api_router.include_router(nodes.router, dependencies=_protected)
api_router.include_router(investigations.router, dependencies=_protected)
api_router.include_router(events.router, dependencies=_protected)
api_router.include_router(settings.router, dependencies=_protected)
api_router.include_router(system.router, dependencies=_protected)
