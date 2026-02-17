from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator, Field
from email_validator import validate_email, EmailNotValidError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import sqlite3
import os

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()

# Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    
    @field_validator('email')
    @classmethod
    def validate_email_deliverability(cls, v: str) -> str:
        """Extra validation: check if domain has MX records"""
        try:
            # This checks if domain can receive emails
            valid = validate_email(v, check_deliverability=True)
            return valid.normalized  # Returns normalized version
        except EmailNotValidError as e:
            raise ValueError(str(e))

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Simple character-based validation (matches frontend)"""
        if len(v) < 8:
            raise ValueError('\nPassword must be at least 8 characters')
        
        if ' ' in v:
            raise ValueError('\nPassword cannot contain spaces')
        
        # Simple character checks (same as frontend)
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        has_special = any(c in '!@#$%^&*(),.?":{}|<>_-+=' for c in v)
        
        missing = []
        if not has_upper: missing.append('uppercase letter')
        if not has_lower: missing.append('lowercase letter')
        if not has_digit: missing.append('number')
        if not has_special: missing.append('special character')
        
        if missing:
            raise ValueError(f"Password must contain at least one {', one '.join(missing)}")
        
        return v

class UserLogin(BaseModel):
    email: EmailStr  # Uses email-validator library automatically
    password: str = Field(min_length=1)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class User(BaseModel):
    id: int
    email: str
    created_at: str

# Database setup
DB_PATH = "users.db"

def init_auth_db():
    """Initialize users database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

# Password utilities
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str: 
    return pwd_context.hash(password)

# JWT utilities
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta  
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15) 
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Database operations
def get_user_by_email(email: str) -> Optional[dict]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, email, hashed_password, created_at FROM users WHERE email = ?",
        (email.lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "email": row[1],
            "hashed_password": row[2],
            "created_at": row[3]
        }
    return None

def create_user(email: str, password: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    hashed_password = get_password_hash(password)
    created_at = datetime.now(timezone.utc).isoformat() + "Z" 
    
    try:
        cursor.execute(
            "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?)",
            (email.lower(), hashed_password, created_at)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        
        return {
            "id": user_id,
            "email": email.lower(),
            "created_at": created_at
        }
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

# Authentication dependency
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Dependency to get current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception
    
    user = get_user_by_email(email=token_data.email)
    if user is None:
        raise credentials_exception
    
    return User(
        id=user["id"],
        email=user["email"],
        created_at=user["created_at"]
    )