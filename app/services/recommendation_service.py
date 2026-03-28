from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import LiveMatch, UpcomingMatch
from app.services.ingame_odds_service import InPlayModelOddsService
from app.services.pregame_odds_service import PreGameOddsService


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_match_identifier(raw: Any) -> int:
    """
    Converte o identificador do jogo para int.

    Casos suportados:
    - int
    - str numérica: "266670"
    - str com separador visual: "266.670"
    - float inteiro: 266670.0
    """
    if raw is None:
        raise ValueError("Identificador do jogo está vazio.")

    if isinstance(raw, bool):
        raise ValueError("Identificador do jogo inválido.")

    if isinstance(raw, int):
        return raw

    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        raise ValueError(f"Identificador do jogo inválido: {raw}")

    text = str(raw).strip()
    if not text:
        raise ValueError("Identificador do jogo está vazio.")

    text = text.replace(".", "").replace(",", "")

    return int(text)


def extract_source_match_id(match_obj: LiveMatch | UpcomingMatch) -> int:
    """
    Regra:
    1. Se existir source_match_id preenchido, usa ele.
    2. Caso contrário, usa o próprio id do registro.
    """
    raw_source = getattr(match_obj, "source_match_id", None)
    if raw_source is not None:
        return _normalize_match_identifier(raw_source)

    raw_id = getattr(match_obj, "id", None)
    return _normalize_match_identifier(raw_id)


def generate_fallback_live_odds(match_obj: LiveMatch) -> dict[str, float]:
    """
    Fallback simples quando o modelo in-play falhar.
    """
    score_diff = (match_obj.score1 or 0) - (match_obj.score2 or 0)
    minute = max(int(match_obj.minute or 0), 0)

    # Base neutra
    home = 2.4
    draw = 3.1
    away = 2.8

    # Ajuste pelo placar
    if score_diff > 0:
        home = max(1.20, home - 0.60 - min(score_diff * 0.20, 0.60))
        draw = min(8.0, draw + 0.50 + min(score_diff * 0.20, 0.60))
        away = min(12.0, away + 1.00 + min(score_diff * 0.35, 1.50))
    elif score_diff < 0:
        away = max(1.20, away - 0.60 - min(abs(score_diff) * 0.20, 0.60))
        draw = min(8.0, draw + 0.50 + min(abs(score_diff) * 0.20, 0.60))
        home = min(12.0, home + 1.00 + min(abs(score_diff) * 0.35, 1.50))

    # Ajuste pelo tempo de jogo
    if minute >= 75 and score_diff == 0:
        draw = max(1.40, draw - 0.90)
        home = min(6.0, home + 0.35)
        away = min(6.0, away + 0.35)
    elif minute >= 75 and score_diff != 0:
        if score_diff > 0:
            home = max(1.05, home - 0.20)
            draw = min(15.0, draw + 0.60)
            away = min(20.0, away + 1.20)
        else:
            away = max(1.05, away - 0.20)
            draw = min(15.0, draw + 0.60)
            home = min(20.0, home + 1.20)

    return {
        "o1": round(home, 2),
        "ox": round(draw, 2),
        "o2": round(away, 2),
    }


def generate_fallback_upcoming_odds(match_obj: UpcomingMatch) -> dict[str, float]:
    """
    Fallback simples para pré-jogo.
    """
    return {
        "o1": 2.35,
        "ox": 3.15,
        "o2": 2.85,
    }


class RecommendationService:
    def __init__(self, db: Session) -> None:
        self.db = db

        self.inplay_service: InPlayModelOddsService | None = None
        self.pregame_service: PreGameOddsService | None = None

        try:
            self.inplay_service = InPlayModelOddsService()
        except Exception as exc:
            print(f"[WARN] InPlayModelOddsService indisponível: {exc}")

        try:
            self.pregame_service = PreGameOddsService()
        except Exception as exc:
            print(f"[WARN] PreGameOddsService indisponível: {exc}")

    def get_live_recommendations(self, limit: int = 10) -> list[dict[str, Any]]:
        matches = (
            self.db.query(LiveMatch)
            .order_by(LiveMatch.league, LiveMatch.id)
            .limit(limit)
            .all()
        )

        result: list[dict[str, Any]] = []

        for live_match in matches:
            item = {
                "id": live_match.id,
                "source_match_id": None,
                "league": live_match.league,
                "team1": live_match.team1,
                "team2": live_match.team2,
                "score1": live_match.score1,
                "score2": live_match.score2,
                "time": str(live_match.minute),
                "status": live_match.status,
                "o1": None,
                "ox": None,
                "o2": None,
            }

            try:
                source_match_id = extract_source_match_id(live_match)
                item["source_match_id"] = source_match_id

                if self.inplay_service is not None:
                    odds_data = self.inplay_service.get_main_market_odds(
                        source_match_id=source_match_id,
                        minute=int(live_match.minute or 0),
                    )
                    market_odds = odds_data.get("market_odds", {})

                    item["o1"] = safe_float(market_odds.get("H"))
                    item["ox"] = safe_float(market_odds.get("D"))
                    item["o2"] = safe_float(market_odds.get("A"))

            except Exception as exc:
                print(f"[WARN] Falha live {live_match.id}: {exc}")

            if item["o1"] is None or item["ox"] is None or item["o2"] is None:
                fallback = generate_fallback_live_odds(live_match)
                item["o1"] = fallback["o1"]
                item["ox"] = fallback["ox"]
                item["o2"] = fallback["o2"]

            result.append(item)

        return result

    def get_upcoming_recommendations(self, limit: int = 10) -> list[dict[str, Any]]:
        matches = (
            self.db.query(UpcomingMatch)
            .order_by(UpcomingMatch.league, UpcomingMatch.id)
            .limit(limit)
            .all()
        )

        result: list[dict[str, Any]] = []

        for upcoming_match in matches:
            item = {
                "id": upcoming_match.id,
                "source_match_id": None,
                "league": upcoming_match.league,
                "team1": upcoming_match.team1,
                "team2": upcoming_match.team2,
                "kickoff_time": upcoming_match.kickoff_time,
                "status": upcoming_match.status,
                "o1": None,
                "ox": None,
                "o2": None,
            }

            try:
                source_match_id = extract_source_match_id(upcoming_match)
                item["source_match_id"] = source_match_id

                if self.pregame_service is not None:
                    odds_data = self.pregame_service.get_main_market_odds(
                        source_match_id=source_match_id
                    )
                    market_odds = odds_data.get("market_odds", {})

                    item["o1"] = safe_float(market_odds.get("H"))
                    item["ox"] = safe_float(market_odds.get("D"))
                    item["o2"] = safe_float(market_odds.get("A"))

            except Exception as exc:
                print(f"[WARN] Falha upcoming {upcoming_match.id}: {exc}")

            if item["o1"] is None or item["ox"] is None or item["o2"] is None:
                fallback = generate_fallback_upcoming_odds(upcoming_match)
                item["o1"] = fallback["o1"]
                item["ox"] = fallback["ox"]
                item["o2"] = fallback["o2"]

            result.append(item)

        return result