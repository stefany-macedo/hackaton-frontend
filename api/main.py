from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(title="Hackaton API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class BetRequest(BaseModel):
    selections: list[dict]
    stake: float
    totalOdd: float


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/users")
def create_user(user: RegisterUser):
    # Backend mínimo: só valida e responde OK.
    return {"id": 1, "email": user.email, "risk_profile": user.risk_profile}


@app.post("/login")
def login(payload: LoginRequest):
    # Backend mínimo: aceita qualquer senha e retorna token fake.
    # Se quiser travar por usuário/senha, dá pra ajustar aqui.
    return {
        "access_token": "fake-jwt-token",
        "token_type": "bearer",
        "risk_profile": "MODERADO",
    }


@app.get("/games/live")
def get_live_games():
    return [
        {
            "id": "g1",
            "league": "Brasileirão",
            "team1": "Flamengo",
            "team2": "Palmeiras",
            "score1": 1,
            "score2": 1,
            "time": "47",
            "o1": "1.85",
            "ox": "3.20",
            "o2": "4.10",
        }
    ]


@app.get("/games/upcoming")
def get_upcoming_games():
    return [
        {
            "id": "u1",
            "league": "Brasileirão",
            "team1": "Santos",
            "team2": "Botafogo",
            "time": "18:00",
            "o1": "2.50",
            "ox": "3.20",
            "o2": "2.80",
        }
    ]


@app.get("/odds/super")
def get_super_odds():
    return [
        {
            "id": "s1",
            "match": "Flamengo x Palmeiras",
            "pick": "Casa (Flamengo)",
            "odd": "3.20",
            "oldOdd": "1.85",
            "league": "Brasileirão",
        }
    ]


@app.post("/bets")
def create_bet(_: BetRequest):
    return {"betId": "bet_123", "status": "confirmed"}

