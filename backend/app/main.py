from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import psycopg
from azure.core.exceptions import ClientAuthenticationError
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.app.config import BackendSettings
from backend.app.dependencies import get_database
from backend.app.errors import ErrorResponse
from backend.app.logging import configure_logging
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database

logger = configure_logging()


def create_app(
    *,
    engine_settings: Settings | None = None,
    backend_settings: BackendSettings | None = None,
    database: Database | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from starlette.concurrency import run_in_threadpool

        from backend.app.services.pipeline_execution import PipelineExecutionService

        settings = engine_settings or Settings.from_env()
        app.state.engine_settings = settings
        app.state.database = database or Database(settings)
        app.state.backend_settings = backend_settings or BackendSettings.from_env()
        service = PipelineExecutionService(app.state.database, settings)
        app.state.execution_service = service
        await run_in_threadpool(service.reconcile_interrupted)
        yield

    app = FastAPI(
        title="S&P 500 Candidate Engine API",
        version="1.0.0",
        description="Candidate and normalized collection records, not investment advice.",
        lifespan=lifespan,
        responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 422, 500, 503)},
    )
    # Configure before startup: App Settings/.env are loaded without replacing supplied values.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[1] / ".env")
    load_dotenv()
    configuration = backend_settings or BackendSettings.from_env()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configuration.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request_complete",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "request_id": request.state.request_id,
            },
        )
        return response

    def error_response(request: Request, status: int, code: str, message: str):
        response = JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )
        origin = request.headers.get("origin")
        if origin in configuration.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        response = error_response(
            request, exc.status_code, f"HTTP_{exc.status_code}", str(exc.detail)
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo submitted credentials or arbitrary request payloads.
        fields = sorted({str(error["loc"][-1]) for error in exc.errors()})
        return error_response(
            request, 422, "VALIDATION_ERROR", "Invalid fields: " + ", ".join(fields)
        )

    @app.exception_handler(psycopg.Error)
    @app.exception_handler(ClientAuthenticationError)
    async def database_error(request: Request, exc: psycopg.Error | ClientAuthenticationError):
        logger.error("database_error", extra={"request_id": request.state.request_id}, exc_info=exc)
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "Database operation failed")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "unexpected_error", extra={"request_id": request.state.request_id}, exc_info=exc
        )
        return error_response(request, 500, "INTERNAL_ERROR", "Unexpected server error")

    @app.get("/health/live", tags=["Health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def ready(db: Annotated[Database, Depends(get_database)]) -> dict[str, str]:
        with db.connect() as connection:
            connection.execute("SELECT 1 FROM ops.backend_pipeline_request LIMIT 1").fetchone()
        return {"status": "ready"}

    from backend.app.routers import (
        candidates,
        collection_data,
        execution,
        pipeline_runs,
        weekly_training,
    )

    for router in (
        candidates.router,
        collection_data.router,
        execution.router,
        pipeline_runs.router,
        weekly_training.router,
    ):
        app.include_router(router)
    return app


def run() -> None:
    import uvicorn

    uvicorn.run("backend.app.main:create_app", factory=True, host="0.0.0.0", port=8000, workers=1)
