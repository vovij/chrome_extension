import os
import uuid
import re
from typing import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from pydantic import field_validator, ValidationError

# ── Config ────────────────────────────────────────────────────────────────────

SECRET = os.getenv("SECRET")
if not SECRET:
    raise RuntimeError(
        "SECRET env var is not set. "
        "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
    )

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./seenit.db")

# ── Database ──────────────────────────────────────────────────────────────────

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    pass  # add extra columns here if needed


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)


# ── User Manager ──────────────────────────────────────────────────────────────

class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request=None):
        print(f"[auth] new user: {user.email}") # can add email verification later if needed

    async def on_after_login(
        self,
        user: User,
        request: Request | None = None, response=None
    ):
        print(f"[auth] user logged in: {user.email}")

async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


# ── Auth backend (JWT Bearer) ─────────────────────────────────────────────────

bearer_transport = BearerTransport(tokenUrl="/api/auth/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=60 * 60 * 24 * 7)  # 7 days


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# ── FastAPIUsers instance ─────────────────────────────────────────────────────

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)

# ── Schemas ───────────────────────────────────────────────────────────────────

class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    """Custom UserCreate with password strength validation"""

    # Override email field to use str instead of EmailStr (bypasses Pydantic's email validation)
    email: str
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Custom email validation with simple error message"""
        # Basic email pattern
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            raise ValueError("Please enter a valid email address")
        
        return v.lower()
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Validate password meets minimum requirements:
        - At least 8 characters
        - At least one uppercase letter
        - At least one digit
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        if not re.search(r'[A-Z]', v) or not re.search(r'\d', v):
            raise ValueError("Password must contain at least one uppercase letter and a number")
        
        return v


# ── DB init ───────────────────────────────────────────────────────────────────

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)