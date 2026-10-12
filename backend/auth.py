from datetime import datetime, timezone
from functools import wraps
from typing import Callable

import bcrypt
import jwt
from flask import jsonify, request

from config import Config
from db import col


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + Config.JWT_ACCESS_EXPIRES,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def get_bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return None


def get_current_user():
    token = get_bearer_token()
    if not token:
        return None
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    user = col("users").find_one({"_id": str(payload["sub"])})
    if not user or user.get("status") == "blocked":
        return None
    return user


def login_required(f: Callable):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        return f(user, *args, **kwargs)

    return wrapper


def role_required(*roles: str):
    def decorator(f: Callable):
        @wraps(f)
        @login_required
        def wrapper(user, *args, **kwargs):
            if user.get("role") not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return f(user, *args, **kwargs)

        return wrapper

    return decorator


def serialize_user(user: dict, include_private: bool = False) -> dict:
    data = {
        "id": str(user["_id"]),
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role", "user"),
        "geographicFocus": user.get("geographic_focus", ""),
        "interests": user.get("interests", []),
        "avatar": user.get("avatar", ""),
        "quizCompleted": bool(user.get("quiz_answers")),
    }
    quiz = user.get("quiz_answers") or {}
    data["preferredStates"] = user.get("preferred_states") or []
    data["favoriteCrafts"] = quiz.get("crafts") or []
    data["preferredRegions"] = quiz.get("regions") or []
    data["workshopInterest"] = quiz.get("workshopInterest", "")
    if include_private:
        data["savedCount"] = col("saved_items").count_documents({"user_id": user["_id"]})
    if user.get("role") == "user":
        app = col("artisan_applications").find_one({"user_id": user["_id"]})
        if app:
            data["applicationStatus"] = app.get("status", "none")
            data["applicationNotes"] = app.get("curator_notes", "")
    return data
