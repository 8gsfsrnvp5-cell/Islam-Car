from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal
from app.request_limits import RequestSizeLimit
from app.routers import (
    admin_accounting,
    admin_agents,
    admin_analytics,
    admin_assistant,
    admin_bank,
    admin_cars,
    admin_checks,
    admin_contracts,
    admin_core,
    admin_crm,
    admin_documents,
    admin_finance,
    admin_knowledge,
    admin_ops,
    auth,
    client,
    online_payments,
    public,
)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Islamic Car API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/api/docs",
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        # Защита от CSRF: изменяющие запросы принимаются только со своих сайтов
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and (
                (origin and origin not in settings.origins)
                or request.headers.get("sec-fetch-site") == "cross-site"
                or (settings.is_production and request.cookies and not origin)):
            return JSONResponse({"detail": "Запрос с недоверенного источника отклонён"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith(("/api/admin", "/api/client", "/api/auth")):
            response.headers["Cache-Control"] = "no-store"
        return response

    for r in (public.router, auth.router, client.router, admin_core.router, admin_cars.router,
              admin_crm.router, admin_contracts.router, admin_documents.router, admin_ops.router,
              admin_knowledge.router, admin_accounting.router, admin_finance.router, admin_checks.router,
              admin_agents.router, admin_bank.router, admin_analytics.router, admin_assistant.router,
              online_payments.router, online_payments.client_router, online_payments.admin_router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        with SessionLocal() as db:
            db.execute(text("select 1"))
        return {"status": "ok", "environment": settings.environment}

    app.add_middleware(RequestSizeLimit, max_bytes=24 * 1024 * 1024)
    return app


app = create_app()
