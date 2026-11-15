import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.http import close_http
from app.services.scheduler import scheduler

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cheker")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    for name, ok in (("Remnawave", settings.remnawave_configured),
                     ("Cloudflare", settings.cloudflare_configured),
                     ("Telegram", settings.telegram_configured)):
        log.info("%s: %s", name, "настроен" if ok else "НЕ настроен")
    scheduler.start()
    yield
    await scheduler.stop()
    await close_http()


app = FastAPI(title="Cheker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(api_router)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


# ---- раздача собранного фронтенда (SPA) ----
if STATIC_DIR.exists():
    if (STATIC_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        file = (STATIC_DIR / full_path).resolve()
        if full_path and file.is_file() and STATIC_DIR in file.parents:
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

