from datetime import datetime
from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    """What the API may reveal about a user (never password hashes)."""
    id: str
    name: str
    email: str
    role: str
    created_at: datetime


class ProfileUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class AccountDelete(BaseModel):
    password: str
