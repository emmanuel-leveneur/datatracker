import pytest
from fastapi.testclient import TestClient


def test_register_first_user_becomes_admin(client: TestClient):
    resp = client.post("/auth/register", data={
        "username": "firstuser",
        "email": "first@test.com",
        "password": "password123",
    })
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_register_duplicate_username(client: TestClient, admin_user):
    resp = client.post("/auth/register", data={
        "username": "admin",
        "email": "other@test.com",
        "password": "password123",
    })
    assert resp.status_code == 400


def test_register_duplicate_email(client: TestClient, admin_user):
    resp = client.post("/auth/register", data={
        "username": "newuser",
        "email": "admin@test.com",
        "password": "password123",
    })
    assert resp.status_code == 400


def test_login_success(client: TestClient, admin_user):
    resp = client.post("/auth/login", data={
        "username": "admin",
        "password": "password123",
    })
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_login_wrong_password(client: TestClient, admin_user):
    resp = client.post("/auth/login", data={
        "username": "admin",
        "password": "wrongpassword",
    })
    assert resp.status_code == 400


def test_login_unknown_user(client: TestClient):
    resp = client.post("/auth/login", data={
        "username": "nobody",
        "password": "password123",
    })
    assert resp.status_code == 400


def test_logout(admin_client: TestClient):
    resp = admin_client.get("/auth/logout")
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_login_page_renders(client: TestClient):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert "Connexion" in resp.text


def test_register_page_renders(client: TestClient):
    resp = client.get("/auth/register")
    assert resp.status_code == 200
    assert "Créer un compte" in resp.text
