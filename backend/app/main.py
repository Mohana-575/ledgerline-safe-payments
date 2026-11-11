from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.accounts import router as accounts_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.movements import router as movements_router
from app.api.routes.statements import router as statements_router
from app.core.exception_handlers import (
    http_exception_handler,
    ledger_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.services.ledger_errors import LedgerError

FRONTEND_DIST = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="LedgerLine API",
    exception_handlers={
        StarletteHTTPException: http_exception_handler,
        LedgerError: ledger_exception_handler,
        RequestValidationError: validation_exception_handler,
        Exception: unhandled_exception_handler,
    },
)
app.include_router(admin_router)
app.include_router(accounts_router)
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(movements_router)
app.include_router(statements_router)

if FRONTEND_DIST.is_dir():

    @app.middleware("http")
    async def serve_spa_navigation(
        request: Request, call_next
    ) -> Response:
        path = request.url.path
        is_frontend_navigation = (
            request.method == "GET"
            and "text/html" in request.headers.get("accept", "").lower()
            and path not in {"/health", "/docs", "/openapi.json", "/redoc"}
            and not path.startswith("/api/")
        )
        if is_frontend_navigation:
            return FileResponse(FRONTEND_DIST / "index.html")
        return await call_next(request)

    @app.get("/", include_in_schema=False)
    def serve_frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend_path(path: str, request: Request) -> FileResponse:
        frontend_root = FRONTEND_DIST.resolve()
        requested_file = (frontend_root / path).resolve()
        try:
            requested_file.relative_to(frontend_root)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found") from None

        if requested_file.is_file():
            return FileResponse(requested_file)
        if "text/html" in request.headers.get("accept", "").lower():
            return FileResponse(frontend_root / "index.html")
        raise HTTPException(status_code=404, detail="Not found")
