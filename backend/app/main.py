from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
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
