import secrets
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import verify_password
from app.models import PasswordResetToken, User


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_token(db: Session, user: User, expired: bool = False, used: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    if expired:
        expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    reset = PasswordResetToken(
        token=token,
        user_id=user.id,
        expires_at=expires_at,
        used_at=datetime.now(timezone.utc) if used else None,
    )
    db.add(reset)
    db.commit()
    return token


# ── Pages ─────────────────────────────────────────────────────────────────────

def test_forgot_password_page_renders(client: TestClient):
    resp = client.get("/auth/forgot-password")
    assert resp.status_code == 200
    assert "Mot de passe oublié" in resp.text


def test_forgot_password_sent_page_renders(client: TestClient, admin_user: User):
    resp = client.post("/auth/forgot-password", data={"email": admin_user.email})
    assert resp.status_code == 200
    assert "Vérifiez votre boîte mail" in resp.text


# ── Demande de reset ──────────────────────────────────────────────────────────

def test_forgot_password_known_email_creates_token(
    client: TestClient, admin_user: User, db: Session
):
    resp = client.post("/auth/forgot-password", data={"email": admin_user.email})
    assert resp.status_code == 200
    token = db.query(PasswordResetToken).filter_by(user_id=admin_user.id).first()
    assert token is not None
    assert token.used_at is None
    assert token.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)


def test_forgot_password_unknown_email_same_response(client: TestClient, db: Session):
    """Pas de token créé, mais réponse identique pour éviter l'énumération d'emails."""
    resp = client.post("/auth/forgot-password", data={"email": "nobody@test.com"})
    assert resp.status_code == 200
    assert "Vérifiez votre boîte mail" in resp.text
    assert db.query(PasswordResetToken).count() == 0


def test_forgot_password_invalidates_previous_token(
    client: TestClient, admin_user: User, db: Session
):
    """Une nouvelle demande invalide les tokens précédents non utilisés."""
    old_token = _make_token(db, admin_user)

    client.post("/auth/forgot-password", data={"email": admin_user.email})

    old = db.query(PasswordResetToken).filter_by(token=old_token).first()
    assert old is None  # supprimé
    assert db.query(PasswordResetToken).filter_by(user_id=admin_user.id).count() == 1


# ── Page reset ────────────────────────────────────────────────────────────────

def test_reset_password_page_valid_token(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    resp = client.get(f"/auth/reset-password?token={token}")
    assert resp.status_code == 200
    assert "Nouveau mot de passe" in resp.text


def test_reset_password_page_expired_token(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user, expired=True)
    resp = client.get(f"/auth/reset-password?token={token}")
    assert resp.status_code == 400
    assert "expiré" in resp.text


def test_reset_password_page_used_token(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user, used=True)
    resp = client.get(f"/auth/reset-password?token={token}")
    assert resp.status_code == 400


def test_reset_password_page_invalid_token(client: TestClient):
    resp = client.get("/auth/reset-password?token=totally-invalid")
    assert resp.status_code == 400


# ── Soumission du nouveau mot de passe ───────────────────────────────────────

def test_reset_password_success(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    resp = client.post("/auth/reset-password", data={
        "token": token,
        "password": "newpassword123",
        "password_confirm": "newpassword123",
    })
    assert resp.status_code == 303
    assert "reset=1" in resp.headers["location"]

    db.refresh(admin_user)
    assert verify_password("newpassword123", admin_user.hashed_password)


def test_reset_password_token_marked_used(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    client.post("/auth/reset-password", data={
        "token": token,
        "password": "newpassword123",
        "password_confirm": "newpassword123",
    })
    reset = db.query(PasswordResetToken).filter_by(token=token).first()
    assert reset.used_at is not None


def test_reset_password_cannot_reuse_token(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    client.post("/auth/reset-password", data={
        "token": token,
        "password": "newpassword123",
        "password_confirm": "newpassword123",
    })
    # Deuxième utilisation du même token
    resp = client.post("/auth/reset-password", data={
        "token": token,
        "password": "anotherpassword",
        "password_confirm": "anotherpassword",
    })
    assert resp.status_code == 400


def test_reset_password_mismatch(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    resp = client.post("/auth/reset-password", data={
        "token": token,
        "password": "newpassword123",
        "password_confirm": "different456",
    })
    assert resp.status_code == 400
    assert "correspondent pas" in resp.text


def test_reset_password_too_short(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user)
    resp = client.post("/auth/reset-password", data={
        "token": token,
        "password": "abc",
        "password_confirm": "abc",
    })
    assert resp.status_code == 400
    assert "8 caractères" in resp.text


def test_reset_password_expired_token_post(
    client: TestClient, admin_user: User, db: Session
):
    token = _make_token(db, admin_user, expired=True)
    resp = client.post("/auth/reset-password", data={
        "token": token,
        "password": "newpassword123",
        "password_confirm": "newpassword123",
    })
    assert resp.status_code == 400

    # Mot de passe inchangé
    db.refresh(admin_user)
    assert verify_password("password123", admin_user.hashed_password)


# ── Login après reset ─────────────────────────────────────────────────────────

def test_login_page_shows_reset_confirmation(client: TestClient):
    resp = client.get("/auth/login?reset=1")
    assert resp.status_code == 200
    assert "nouveau mot de passe" in resp.text.lower()
