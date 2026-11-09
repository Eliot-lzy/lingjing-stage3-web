from __future__ import annotations

from pydantic import BaseModel


class Credentials(BaseModel):
    email: str
    password: str


class TaskUpdate(BaseModel):
    title: str
