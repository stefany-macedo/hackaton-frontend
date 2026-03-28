from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db, settings
from app.models import LiveMatch, UpcomingMatch, User, UserBet
from app.schemas import BetRequest, CouponComposeRequest, LoginRequest, RegisterUser
from app.services.coupon_service import CouponService
from app.services.ingame_odds_service import InPlayModelOddsService
from app.services.pregame_odds_service import PreGameOddsService
from app.services.recommendation_service import RecommendationService
from app.services.user_profile_service import UserProfileService
from app.services.match_sync_service import MatchSyncService

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.api_title, version=settings.api_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_source_match_id(match_obj) -> int:
    source_match_id = getattr(match_obj, "source_match_id", None)
    if source_match_id is not None:
        return int(source_match_id)

    raw_id = str(match_obj.id)

    if raw_id.startswith("live_"):
        return int(raw_id.replace("live_", ""))

    if raw_id.startswith("upcoming_"):
        return int(raw_id.replace("upcoming_", ""))

    return int(raw_id)


def safe_float(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def generate_fallback_live_odds(match: LiveMatch) -> dict[str, float]:
    home_score = int(match.score1 or 0)
    away_score = int(match.score2 or 0)
    minute = int(match.minute or 1)

    goal_diff = home_score - away_score

    home_prob = 0.45
    draw_prob = 0.28
    away_prob = 0.27

    home_prob += goal_diff * 0.12
    away_prob -= goal_diff * 0.12

    time_factor = min(max(minute / 90.0, 0.0), 1.0)
    draw_prob -= abs(goal_diff) * 0.05 * (1 + time_factor)

    if goal_diff > 0:
        home_prob += 0.10 * time_factor
        away_prob -= 0.05 * time_factor
    elif goal_diff < 0:
        away_prob += 0.10 * time_factor
        home_prob -= 0.05 * time_factor

    probs = [max(home_prob, 0.05), max(draw_prob, 0.05), max(away_prob, 0.05)]
    total = sum(probs)
    probs = [p / total for p in probs]

    margin = 1.06
    o1 = round(max(1.01, 1 / (probs[0] * margin)), 2)
    ox = round(max(1.01, 1 / (probs[1] * margin)), 2)
    o2 = round(max(1.01, 1 / (probs[2] * margin)), 2)

    return {"o1": o1, "ox": ox, "o2": o2}


def generate_fallback_upcoming_odds(match: UpcomingMatch) -> dict[str, float]:
    team_hash = abs(hash(f"{match.team1}-{match.team2}")) % 100

    home_prob = 0.40 + (team_hash % 7) * 0.01
    draw_prob = 0.28
    away_prob = 1.0 - home_prob - draw_prob

    probs = [max(home_prob, 0.20), max(draw_prob, 0.20), max(away_prob, 0.20)]
    total = sum(probs)
    probs = [p / total for p in probs]

    margin = 1.06
    o1 = round(max(1.01, 1 / (probs[0] * margin)), 2)
    ox = round(max(1.01, 1 / (probs[1] * margin)), 2)
    o2 = round(max(1.01, 1 / (probs[2] * margin)), 2)

    return {"o1": o1, "ox": ox, "o2": o2}


def build_fallback_live_markets(match: LiveMatch) -> list[dict]:
    odds = generate_fallback_live_odds(match)

    return [
        {
            "market_type": "1x2",
            "market_name": "Resultado Final",
            "options": [
                {
                    "selection_key": "home",
                    "selection_label": f"{match.team1} vence",
                    "market_odd": odds["o1"],
                    "model_odd": odds["o1"],
                    "model_probability": round(1 / odds["o1"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
                {
                    "selection_key": "draw",
                    "selection_label": "Empate",
                    "market_odd": odds["ox"],
                    "model_odd": odds["ox"],
                    "model_probability": round(1 / odds["ox"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
                {
                    "selection_key": "away",
                    "selection_label": f"{match.team2} vence",
                    "market_odd": odds["o2"],
                    "model_odd": odds["o2"],
                    "model_probability": round(1 / odds["o2"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
            ],
        }
    ]


def build_fallback_upcoming_markets(match: UpcomingMatch) -> list[dict]:
    odds = generate_fallback_upcoming_odds(match)

    return [
        {
            "market_type": "1x2",
            "market_name": "Resultado Final",
            "options": [
                {
                    "selection_key": "home",
                    "selection_label": f"{match.team1} vence",
                    "market_odd": odds["o1"],
                    "model_odd": odds["o1"],
                    "model_probability": round(1 / odds["o1"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
                {
                    "selection_key": "draw",
                    "selection_label": "Empate",
                    "market_odd": odds["ox"],
                    "model_odd": odds["ox"],
                    "model_probability": round(1 / odds["ox"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
                {
                    "selection_key": "away",
                    "selection_label": f"{match.team2} vence",
                    "market_odd": odds["o2"],
                    "model_odd": odds["o2"],
                    "model_probability": round(1 / odds["o2"], 6),
                    "edge_pct": 0.0,
                    "risk_level": "medio",
                },
            ],
        }
    ]


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/users")
def create_user(user: RegisterUser, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="E-mail já cadastrado.")

    new_user = User(
        nome=user.nome,
        sobrenome=user.sobrenome,
        email=user.email,
        cpf=user.cpf,
        telefone=user.telefone,
        password_hash=user.password_hash,
        risk_profile=user.risk_profile,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "email": new_user.email,
        "risk_profile": new_user.risk_profile,
    }


@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Credenciais inválidas.")

    return {
        "access_token": "fake-jwt-token",
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "risk_profile": user.risk_profile,
            "email": user.email,
        },
    }

@app.get("/admin/sync-matches")
def sync_matches(db: Session = Depends(get_db)):
    service = MatchSyncService(db)
    result = service.sync_all(limit_upcoming=10, limit_live=10)
    return {
        "message": "Sincronização concluída com sucesso.",
        **result,
    }

@app.get("/games/live")
def get_live_games(db: Session = Depends(get_db)):
    matches = (
        db.query(LiveMatch)
        .order_by(LiveMatch.league, LiveMatch.id)
        .limit(10)
        .all()
    )

    result = []

    model_service = None
    try:
        model_service = InPlayModelOddsService()
    except Exception as exc:
        print(f"[WARN] InPlayModelOddsService indisponível: {exc}")

    for m in matches:
        item = {
            "id": m.id,
            "source_match_id": None,
            "league": m.league,
            "team1": m.team1,
            "team2": m.team2,
            "score1": m.score1,
            "score2": m.score2,
            "time": str(m.minute),
            "status": m.status,
            "o1": None,
            "ox": None,
            "o2": None,
        }

        try:
            source_match_id = extract_source_match_id(m)
            item["source_match_id"] = source_match_id

            if model_service is not None:
                odds_data = model_service.get_main_market_odds(
                    source_match_id=source_match_id,
                    minute=int(m.minute or 0),
                )
                market_odds = odds_data.get("market_odds", {})

                item["o1"] = safe_float(market_odds.get("H"))
                item["ox"] = safe_float(market_odds.get("D"))
                item["o2"] = safe_float(market_odds.get("A"))

        except Exception as exc:
            print(f"[WARN] Falha live {m.id}: {exc}")

        if item["o1"] is None or item["ox"] is None or item["o2"] is None:
            fallback = generate_fallback_live_odds(m)
            item["o1"] = fallback["o1"]
            item["ox"] = fallback["ox"]
            item["o2"] = fallback["o2"]

        result.append(item)

    return result

@app.get("/games/upcoming")
def get_upcoming_games(db: Session = Depends(get_db)):
    matches = (
        db.query(UpcomingMatch)
        .order_by(UpcomingMatch.league, UpcomingMatch.id)
        .limit(10)
        .all()
    )

    result = []

    model_service = None
    try:
        model_service = PreGameOddsService()
    except Exception as exc:
        print(f"[WARN] PreGameOddsService indisponível: {exc}")

    for m in matches:
        item = {
            "id": m.id,
            "source_match_id": None,
            "league": m.league,
            "team1": m.team1,
            "team2": m.team2,
            "time": m.kickoff_time,
            "status": m.status,
            "o1": None,
            "ox": None,
            "o2": None,
        }

        try:
            source_match_id = extract_source_match_id(m)
            item["source_match_id"] = source_match_id

            if model_service is not None:
                odds_data = model_service.get_main_market_odds(
                    source_match_id=source_match_id,
                )
                market_odds = odds_data.get("market_odds", {})

                item["o1"] = safe_float(market_odds.get("H"))
                item["ox"] = safe_float(market_odds.get("D"))
                item["o2"] = safe_float(market_odds.get("A"))

        except Exception as exc:
            print(f"[WARN] Falha upcoming {m.id}: {exc}")

        if item["o1"] is None or item["ox"] is None or item["o2"] is None:
            fallback = generate_fallback_upcoming_odds(m)
            item["o1"] = fallback["o1"]
            item["ox"] = fallback["ox"]
            item["o2"] = fallback["o2"]

        result.append(item)

    return result


@app.get("/games/{match_id}/markets")
def get_match_markets(match_id: str, db: Session = Depends(get_db)):
    live_match = db.get(LiveMatch, match_id)
    if live_match:
        try:
            model_service = InPlayModelOddsService()
            source_match_id = extract_source_match_id(live_match)
            markets = model_service.build_markets_from_model(
                source_match_id=source_match_id,
                minute=live_match.minute,
                home_team=live_match.team1,
                away_team=live_match.team2,
            )
            return {"match_id": live_match.id, "markets": markets}
        except Exception as exc:
            print(f"[WARN] Fallback markets live {live_match.id}: {exc}")
            return {
                "match_id": live_match.id,
                "markets": build_fallback_live_markets(live_match),
            }

    upcoming_match = db.get(UpcomingMatch, match_id)
    if upcoming_match:
        try:
            model_service = PreGameOddsService()
            source_match_id = extract_source_match_id(upcoming_match)
            markets = model_service.build_markets_from_model(
                source_match_id=source_match_id,
                home_team=upcoming_match.team1,
                away_team=upcoming_match.team2,
            )
            return {"match_id": upcoming_match.id, "markets": markets}
        except Exception as exc:
            print(f"[WARN] Fallback markets upcoming {upcoming_match.id}: {exc}")
            return {
                "match_id": upcoming_match.id,
                "markets": build_fallback_upcoming_markets(upcoming_match),
            }

    raise HTTPException(status_code=404, detail="Partida não encontrada.")


@app.get("/users/{user_id}/profile")
def get_user_profile(user_id: str, db: Session = Depends(get_db)):
    service = UserProfileService(db)
    try:
        return service.get_profile(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/recommendations/live/{match_id}")
def get_live_recommendations(match_id: str, db: Session = Depends(get_db)):
    service = RecommendationService(db)
    try:
        recommendations = service.get_live_recommendations(limit=200)
        match_data = next((item for item in recommendations if item["id"] == match_id), None)

        if not match_data:
            raise ValueError(f"Partida {match_id} não encontrada.")

        return {
            "match_id": match_id,
            "recommendations": [
                {
                    "market_type": "1x2",
                    "selection_key": "home",
                    "selection_label": f"{match_data['team1']} vence",
                    "market_odd": float(match_data["o1"]),
                    "risk_level": "medio",
                    "recommendation_score": round(1 / float(match_data["o1"]), 6),
                },
                {
                    "market_type": "1x2",
                    "selection_key": "draw",
                    "selection_label": "Empate",
                    "market_odd": float(match_data["ox"]),
                    "risk_level": "baixo",
                    "recommendation_score": round(1 / float(match_data["ox"]), 6),
                },
                {
                    "market_type": "1x2",
                    "selection_key": "away",
                    "selection_label": f"{match_data['team2']} vence",
                    "market_odd": float(match_data["o2"]),
                    "risk_level": "alto",
                    "recommendation_score": round(1 / float(match_data["o2"]), 6),
                },
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/coupon/compose")
def compose_coupon(payload: CouponComposeRequest, db: Session = Depends(get_db)):
    service = CouponService(db)
    try:
        return service.compose_coupon(
            user_id=payload.user_id,
            matches=payload.matches,
            max_selections=payload.max_selections,
            target_risk=payload.target_risk,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/bets")
def create_bet(payload: BetRequest, db: Session = Depends(get_db)):
    if not payload.selections:
        raise HTTPException(status_code=400, detail="Nenhuma seleção enviada.")

    # Regra: no mercado 1x2, só pode existir uma seleção por partida
    selections_1x2_by_match = {}

    for selection in payload.selections:
        if selection.market_type == "1x2":
            if selection.match_id in selections_1x2_by_match:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Não é permitido apostar em mais de uma seleção do mercado 1x2 "
                        f"para a mesma partida ({selection.match_id})."
                    ),
                )
            selections_1x2_by_match[selection.match_id] = selection.selection_key

    bet_ids = []
    potential_payout = round(payload.stake * payload.totalOdd, 2)

    for selection in payload.selections:
        bet = UserBet(
            user_id=payload.user_id,
            match_id=selection.match_id,
            market_type=selection.market_type,
            selection_key=selection.selection_key,
            selection_label=selection.selection_label,
            odd_taken=selection.odd_taken,
            stake=payload.stake,
            potential_payout=potential_payout,
        )
        db.add(bet)
        db.flush()
        bet_ids.append(bet.id)

    db.commit()

    return {
        "betId": bet_ids[0],
        "status": "confirmed",
        "potential_payout": potential_payout,
    }