import os
import re
import traceback
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import AsyncGenerator

import aiosmtplib
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from pydantic import field_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


# config

SECRET = os.getenv("SECRET")
if not SECRET:
    raise RuntimeError(
        "SECRET env var is not set. "
        "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR}/seenit.db")

print(f"[auth] DATABASE_URL = {DATABASE_URL}")


# database

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    pass


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)


# email

async def send_verification_email(to_email: str, verify_url: str) -> None:
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_password:
        raise RuntimeError("SMTP_USER and SMTP_PASSWORD must be set")

    message = MIMEMultipart("alternative")
    message["Subject"] = "Verify your SeenIt account"
    message["From"] = smtp_from
    message["To"] = to_email

    message.attach(MIMEText(f"Welcome to SeenIt!\n\nVerify your account here:\n{verify_url}", "plain"))
    message.attach(MIMEText(f"""
    <html><body>
        <p>Welcome to SeenIt!</p>
        <p><a href="{verify_url}">Verify my account</a></p>
        <p>Or copy this link: {verify_url}</p>
    </body></html>
    """, "html"))

    try:
        await aiosmtplib.send(
            message,
            hostname="smtp.gmail.com",
            port=465,
            username=smtp_user,
            password=smtp_password,
            use_tls=True,
            start_tls=False,
            timeout=30,
        )
        print(f"[auth] verification email sent to {to_email}")
    except Exception as exc:
        print(f"[auth] SMTP send failed: {repr(exc)}")
        traceback.print_exc()
        raise


# user manager

class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Request | None = None):
        try:
            await self.request_verify(user, request)
            print(f"[auth] verification requested for {user.email}")
        except Exception as exc:
            print(f"[auth] failed to request verify: {repr(exc)}")
            traceback.print_exc()

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None):
        try:
            verify_url = f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/verify-email?token={token}"
            await send_verification_email(user.email, verify_url)
        except Exception as exc:
            print(f"[auth] failed to send email: {repr(exc)}")
            traceback.print_exc()

    async def on_after_verify(self, user: User, request: Request | None = None):
        print(f"[auth] user verified: {user.email}")

    async def on_after_login(self, user: User, request: Request | None = None, response=None, **kwargs):
        print(f"[auth] user logged in: {user.email}")


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


# auth backend (JWT Bearer)

bearer_transport = BearerTransport(tokenUrl="/api/auth/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=60 * 60 * 24 * 7)  # 7 days


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True, verified=True)


# schemas

class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError("Please enter a valid email address")
        return v.lower()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r'[A-Z]', v) or not re.search(r'\d', v):
            raise ValueError("Password must contain at least one uppercase letter and a number")
        return v


# db init

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)