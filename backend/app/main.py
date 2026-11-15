import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core import integrations
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.http import close_http
from app.services import settings_service
from app.services.scheduler import scheduler

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cheker")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await integrations.load(db)
        await settings_service.migrate(db)
    for name, ok in (("Remnawave", integrations.remnawave_configured()),
                     ("Cloudflare", integrations.cloudflare_configured()),
                     ("Telegram", integrations.telegram_configured())):
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
