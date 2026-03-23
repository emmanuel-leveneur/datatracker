from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.auth import clear_session, create_session, hash_password, verify_password
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(username=username).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Identifiants incorrects"},
            status_code=400,
        )
    resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    create_session(resp, user.id)
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "auth/register.html")


@router.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).filter_by(username=username).first():
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Ce nom d'utilisateur est déjà pris"},
            status_code=400,
        )
    if db.query(User).filter_by(email=email).first():
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Cet email est déjà utilisé"},
            status_code=400,
        )
    is_first = db.query(User).count() == 0
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_admin=is_first,
    )
    db.add(user)
    db.commit()
    return RedirectResponse(url="/auth/login?registered=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session(resp)
    return resp
