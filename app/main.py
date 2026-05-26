import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.database import create_tables
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import auth, tables, data, export, permissions, admin, logs, tracabilite
from app.routers import alerts as alerts_router
from app.routers import import_auto as import_auto_router
from app.routers import comments as comments_router
from app.routers import sync as sync_router
from app.routers import attachments as attachments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="DataTracker", lifespan=lifespan)
_REUNION_TZ = timezone(timedelta(hours=4))


def _dt_reunion(dt: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_REUNION_TZ).strftime(fmt)


from app.config import settings as _settings

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = json.loads
templates.env.filters["dt_reunion"] = _dt_reunion
templates.env.globals["org_name"] = _settings.ORG_NAME
templates.env.globals["dpo_email"] = _settings.DPO_EMAIL

app.include_router(auth.router)
app.include_router(tables.router)
app.include_router(data.router)
app.include_router(export.router)
app.include_router(permissions.router)
app.include_router(admin.router)
app.include_router(logs.router)
app.include_router(tracabilite.router)
app.include_router(alerts_router.router)
app.include_router(import_auto_router.router)
app.include_router(comments_router.router)
app.include_router(sync_router.router)
app.include_router(attachments_router.router)

# Propagate dt_reunion filter to every router's Jinja2Templates instance
_router_modules = [
    auth, tables, data, export, permissions, admin, logs, tracabilite,
    alerts_router, import_auto_router, comments_router, sync_router, attachments_router,
]
for _mod in _router_modules:
    if hasattr(_mod, "templates"):
        _mod.templates.env.filters["dt_reunion"] = _dt_reunion
        _mod.templates.env.globals["org_name"] = _settings.ORG_NAME
        _mod.templates.env.globals["dpo_email"] = _settings.DPO_EMAIL


@app.get("/")
def root(request: Request):
    from app.auth import get_session_user_id
    user_id = get_session_user_id(request)
    if user_id:
        return RedirectResponse(url="/tables/")
    return RedirectResponse(url="/auth/login")


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return templates.TemplateResponse(
        "errors/403.html", {"request": request}, status_code=403
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "errors/404.html", {"request": request}, status_code=404
    )
