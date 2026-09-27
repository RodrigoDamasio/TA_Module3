import os

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/users")
users: dict[str, dict] = {}


class Register(BaseModel):
    email: str
    password: str
    name: str | None = None


class Login(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
def register(body: Register) -> dict:
    if body.email in users:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt())
    users[body.email] = {"email": body.email, "name": body.name, "password": hashed}
    return {"email": body.email, "name": body.name}


@router.post("/login")
def login(body: Login) -> dict:
    user = users.get(body.email)
    if not user or not bcrypt.checkpw(body.password.encode(), user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"email": body.email}, os.environ["JWT_SECRET"], algorithm="HS256")
    return {"token": token}


@router.get("/{email}")
def profile(email: str) -> dict:
    user = users.get(email)
    if not user:
        raise HTTPException(status_code=404, detail="Not found")
    return {"email": user["email"], "name": user["name"]}
