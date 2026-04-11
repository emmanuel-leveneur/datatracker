import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.auth import hash_password, serializer, SESSION_COOKIE

# Base de données en mémoire partagée — isolation par create_all/drop_all par test
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
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
        is_email_verified=True,
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
        is_email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def second_user(db):
    user = User(
        username="bob",
        email="bob@test.com",
        hashed_password=hash_password("password123"),
        is_admin=False,
        is_email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _authenticated_client(client, user_id):
    token = serializer.dumps({"user_id": user_id})
    client.cookies.set(SESSION_COOKIE, token)
    return client


@pytest.fixture
def admin_client(client, admin_user):
    return _authenticated_client(client, admin_user.id)


@pytest.fixture
def user_client(client, regular_user):
    return _authenticated_client(client, regular_user.id)
