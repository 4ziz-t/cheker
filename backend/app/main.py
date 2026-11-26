import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core import integrations
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.http import close_http
from app.services import domain_service, settings_service
from app.services.scheduler import scheduler
from app.services.speed import tracker

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cheker")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with SessionLocal() as db:
        await integrations.load(db)
        await settings_service.migrate(db)
        # новые правила итога (большинство источников, «в реестре» ≠ бан) — пересчитать один раз
        if not await settings_service.get_state(db, "migrated_majority_vote"):
            try:
                fixed = await domain_service.recompute_stored(db)
                log.info("Итог IP пересчитан по новым правилам: изменено %d", fixed)
            except Exception:
                log.exception("Не удалось пересчитать итог IP")
            await settings_service.set_state(db, "migrated_majority_vote", True)
            await db.commit()
        try:
            points = await tracker.load(db)
            log.info("История скорости нод: восстановлено точек — %d", points)
        except Exception:  # без истории норма просто наберётся заново
            log.exception("Не удалось загрузить историю скорости нод")
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
