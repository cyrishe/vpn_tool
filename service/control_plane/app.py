from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import build_api_router
from .config import Settings
from .database import Database
from .errors import APIError
from .seed import seed_development_data


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    database = Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_schema()
        if resolved_settings.seed_demo_data:
            with database.session_factory() as session:
                seed_development_data(session, resolved_settings)
        yield
        database.dispose()

    app = FastAPI(
        title="Regional VPN Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.settings = resolved_settings

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message},
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request payload or parameters are invalid.",
                    "details": exc.errors(),
                },
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    app.include_router(build_api_router(resolved_settings))
    return app


app = create_app()

