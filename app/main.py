"""Application factory. The module-level app is what uvicorn loads."""

import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

mimetypes.add_type("font/woff2", ".woff2")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.seed import seed_if_empty
from app.web import router


def create_app(data_dir: str | os.PathLike | None = None) -> FastAPI:
    data = Path(data_dir or os.environ.get("DATA_DIR", "data")).resolve()
    data.mkdir(parents=True, exist_ok=True)
    upload = data / "uploads"
    upload.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{data / 'healthcheck.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = session_factory()
        try:
            seed_if_empty(db, upload)
            db.commit()
        finally:
            db.close()
        yield

    app = FastAPI(title="月度遠端健康檢查", lifespan=lifespan)
    app.state.Session = session_factory
    app.state.upload_dir = upload
    app.state.data_dir = data

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(router)
    return app


app = create_app()
