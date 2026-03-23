import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.auth import hash_password, create_session

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
    user = User(
        username="admin",
        email="admin@test.com",
        hashed_password=hash_password("password123"),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db):
    user = User(
        username="alice",
        email="alice@test.com",
        hashed_password=hash_password("password123"),
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_client(client, admin_user):
    """Client with admin session cookie."""
    from app.auth import serializer, SESSION_COOKIE
    token = serializer.dumps({"user_id": admin_user.id})
    client.cookies.set(SESSION_COOKIE, token)
    return client


@pytest.fixture
def user_client(client, regular_user):
    """Client with regular user session cookie."""
    from app.auth import serializer, SESSION_COOKIE
    token = serializer.dumps({"user_id": regular_user.id})
    client.cookies.set(SESSION_COOKIE, token)
    return client
