import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response

SECRET_KEY = "change-me-in-production-use-env-var"
SESSION_COOKIE = "dt_session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 days

serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_session(response: Response, user_id: int) -> None:
    token = serializer.dumps({"user_id": user_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
    )


def get_session_user_id(request: Request) -> int | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = serializer.loads(token, max_age=MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)
