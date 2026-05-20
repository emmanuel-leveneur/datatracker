import logging
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.activity import log_action
from app.auth import (
    clear_session, create_session, generate_email_token,
    hash_password, verify_email_token, verify_password,
)
from app.config import settings
from app.database import get_db
from app.email_utils import send_confirmation_email, send_password_reset_email
from app.models import PasswordResetToken, User

logger = logging.getLogger(__name__)

RESET_TOKEN_EXPIRY_MINUTES = 30

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(email=email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Identifiants incorrects"},
            status_code=400,
        )
    if not user.is_email_verified:
        return templates.TemplateResponse(
            request, "auth/login.html",
            {"error": "Veuillez confirmer votre adresse email avant de vous connecter."},
            status_code=403,
        )
    log_action(db, user, "login", "user", resource_name=user.email.split("@")[0])
    db.commit()
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
    existing_by_email = db.query(User).filter_by(email=email).first()
    existing_by_username = db.query(User).filter_by(username=username).first()

    # Username pris par un compte vérifié ou par un compte avec un email différent
    if existing_by_username:
        if existing_by_username.is_email_verified or existing_by_username.email != email:
            return templates.TemplateResponse(
                request, "auth/register.html",
                {"error": "Ce nom d'utilisateur est déjà pris"},
                status_code=400,
            )

    # Email pris par un compte vérifié
    if existing_by_email and existing_by_email.is_email_verified:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Cet email est déjà utilisé"},
            status_code=400,
        )

    # Écraser le compte non vérifié existant avec ce même email
    if existing_by_email and not existing_by_email.is_email_verified:
        db.delete(existing_by_email)
        db.flush()

    is_first = db.query(User).count() == 0
    smtp_configured = bool(settings.SMTP_HOST)

    # Premier compte (admin) ou SMTP non configuré → validé directement
    is_verified = is_first or not smtp_configured

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_admin=is_first,
        is_email_verified=is_verified,
    )
    db.add(user)
    db.flush()
    log_action(db, user, "register", "user",
               resource_id=user.id, resource_name=user.email.split("@")[0],
               details="Admin" if is_first else "")
    db.commit()

    if is_verified:
        return RedirectResponse(url="/auth/login?registered=1", status_code=status.HTTP_303_SEE_OTHER)

    # Envoi de l'email de confirmation
    token = generate_email_token(user.id)
    confirmation_url = f"{settings.APP_URL.rstrip('/')}/auth/confirm-email?token={token}"
    send_confirmation_email(
        to_address=email,
        username=username,
        confirmation_url=confirmation_url,
    )
    return templates.TemplateResponse(request, "auth/confirm_email_sent.html", {"email": email})


@router.get("/confirm-email", response_class=HTMLResponse)
def confirm_email(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    user_id = verify_email_token(token)
    if user_id is None:
        return templates.TemplateResponse(
            request, "auth/confirm_email_error.html", {}, status_code=400
        )

    user = db.get(User, user_id)
    if not user or user.is_email_verified:
        # Déjà vérifié ou compte supprimé → redirect login sans erreur
        return RedirectResponse(url="/auth/login?confirmed=1", status_code=status.HTTP_303_SEE_OTHER)

    user.is_email_verified = True
    db.commit()
    return RedirectResponse(url="/auth/login?confirmed=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session(resp)
    return resp


# ── Mot de passe oublié ────────────────────────────────────────────────────────

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html", {})


@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(email=email.strip().lower()).first()
    if user:
        # Invalider les anciens tokens non utilisés pour cet utilisateur
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at == None,
        ).delete()

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)
        db.add(PasswordResetToken(
            token=token,
            user_id=user.id,
            expires_at=expires_at,
        ))
        db.commit()

        reset_url = f"{settings.APP_URL.rstrip('/')}/auth/reset-password?token={token}"
        send_password_reset_email(
            to_address=user.email,
            username=user.username,
            reset_url=reset_url,
        )
        logger.info("Password reset requested for user_id=%s", user.id)

    # Réponse identique qu'il existe ou non — évite l'énumération d'emails
    return templates.TemplateResponse(request, "auth/forgot_password_sent.html", {"email": email})


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
):
    reset = _get_valid_token(token, db)
    if reset is None:
        return templates.TemplateResponse(
            request, "auth/reset_password_error.html", {}, status_code=400
        )
    return templates.TemplateResponse(request, "auth/reset_password.html", {"token": token})


@router.post("/reset-password", response_class=HTMLResponse)
def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return templates.TemplateResponse(
            request, "auth/reset_password.html",
            {"token": token, "error": "Les mots de passe ne correspondent pas."},
            status_code=400,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "auth/reset_password.html",
            {"token": token, "error": "Le mot de passe doit contenir au moins 8 caractères."},
            status_code=400,
        )

    reset = _get_valid_token(token, db)
    if reset is None:
        return templates.TemplateResponse(
            request, "auth/reset_password_error.html", {}, status_code=400
        )

    reset.user.hashed_password = hash_password(password)
    reset.used_at = datetime.now(timezone.utc)
    log_action(db, reset.user, "reset_password", "user",
               resource_id=reset.user.id, resource_name=reset.user.email.split("@")[0])
    db.commit()

    return RedirectResponse(url="/auth/login?reset=1", status_code=status.HTTP_303_SEE_OTHER)


def _get_valid_token(token: str, db: Session) -> PasswordResetToken | None:
    """Retourne le token s'il est valide (existe, non expiré, non utilisé)."""
    reset = db.query(PasswordResetToken).filter_by(token=token).first()
    if not reset:
        return None
    if reset.used_at is not None:
        return None
    expires = reset.expires_at.replace(tzinfo=timezone.utc) if reset.expires_at.tzinfo is None else reset.expires_at
    if datetime.now(timezone.utc) > expires:
        return None
    return reset
