from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    sobrenome: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    cpf: Mapped[str] = mapped_column(String(11), unique=True, nullable=False)
    telefone: Mapped[str] = mapped_column(String(11), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    risk_profile: Mapped[str] = mapped_column(String(20), default="MODERADO", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    bets: Mapped[list["UserBet"]] = relationship(back_populates="user")


class LiveMatch(Base):
    __tablename__ = "live_matches"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_match_id: Mapped[int | None] = mapped_column(nullable=True, unique=True, index=True)
    league: Mapped[str] = mapped_column(String(100), nullable=False)
    team1: Mapped[str] = mapped_column(String(100), nullable=False)
    team2: Mapped[str] = mapped_column(String(100), nullable=False)
    score1: Mapped[int] = mapped_column(Integer, default=0)
    score2: Mapped[int] = mapped_column(Integer, default=0)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="LIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    markets: Mapped[list["LiveMarketOdd"]] = relationship(back_populates="match")


class LiveMarketOdd(Base):
    __tablename__ = "live_market_odds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    match_id: Mapped[str] = mapped_column(ForeignKey("live_matches.id"), nullable=False, index=True)
    market_type: Mapped[str] = mapped_column(String(100), nullable=False)
    market_name: Mapped[str] = mapped_column(String(255), nullable=False)
    selection_key: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_label: Mapped[str] = mapped_column(String(255), nullable=False)
    market_odd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    model_probability: Mapped[float] = mapped_column(Float, nullable=False)
    model_fair_odd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    edge_pct: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    match: Mapped["LiveMatch"] = relationship(back_populates="markets")


class UserBet(Base):
    __tablename__ = "user_bets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    match_id: Mapped[str] = mapped_column(String(50), nullable=False)
    market_type: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_key: Mapped[str] = mapped_column(String(100), nullable=False)
    selection_label: Mapped[str] = mapped_column(String(255), nullable=False)
    odd_taken: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    stake: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    potential_payout: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    user: Mapped["User"] = relationship(back_populates="bets")


class UpcomingMatch(Base):
    __tablename__ = "upcoming_matches"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    source_match_id: Mapped[int] = mapped_column(nullable=False, unique=True, index=True)
    league: Mapped[str] = mapped_column(String(100), nullable=False)
    team1: Mapped[str] = mapped_column(String(100), nullable=False)
    team2: Mapped[str] = mapped_column(String(100), nullable=False)
    kickoff_time: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="UPCOMING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)