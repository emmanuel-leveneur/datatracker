from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.database import create_tables
from app.scheduler import start_scheduler, stop_scheduler
from app.routers import auth, tables, data, export, permissions, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="DataTracker", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(tables.router)
app.include_router(data.router)
app.include_router(export.router)
app.include_router(permissions.router)
app.include_router(admin.router)


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
