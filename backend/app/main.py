import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    passphrase = get_settings().credentials_passphrase
    if passphrase:
        from app.services.credentials_sync import sync
        try:
            changed, missing = sync(passphrase)
            logger.info("Файл паролей: обновлено %s, номеров без пользователя: %s", changed, len(missing))
        except Exception as exc:  # сервер должен стартовать, даже если файл не прочитан
            logger.error("Файл паролей не загружен: %s", exc)
    yield


app = FastAPI(title="Платформа охраны труда", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(api_router)


@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    return {"status": "ok"}


class WebFiles(StaticFiles):
    """Файлы интерфейса: браузер перепроверяет их при каждом открытии (по ETag — без повторной
    загрузки, если файл не менялся), поэтому после обновления сайта не остаётся старой версии."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Веб-интерфейс (без сборки, ~15 КБ). Подключается последним, чтобы не перекрывать API и /docs.
app.mount("/", WebFiles(directory=Path(__file__).parent / "static", html=True), name="web")
