from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field
from typing import Literal


class RegisterUser(BaseModel):
    nome: str = Field(min_length=2)
    sobrenome: str | None = None
    email: EmailStr
    cpf: str = Field(min_length=11, max_length=11)
    telefone: str = Field(min_length=10, max_length=11)
    password_hash: str = Field(min_length=1)
    risk_profile: str = Field(default="MODERADO")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class BetSelection(BaseModel):
    match_id: str
    market_type: str
    selection_key: str
    selection_label: str
    odd_taken: float


class BetRequest(BaseModel):
    user_id: str
    selections: list[BetSelection]
    stake: float
    totalOdd: float


class CouponComposeRequest(BaseModel):
    user_id: str
    matches: list[str]
    max_selections: int = 3
    target_risk: Literal["SAFE", "MODERADO", "RISCO"] = "MODERADO"