from __future__ import annotations

from statistics import median
from sqlalchemy.orm import Session

from app.models import User, UserBet


class UserProfileService:
    def __init__(self, db: Session):
        self.db = db

    def get_profile(self, user_id: str) -> dict:
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("Usuário não encontrado.")

        bets = (
            self.db.query(UserBet)
            .filter(UserBet.user_id == user_id)
            .order_by(UserBet.placed_at.desc())
            .all()
        )

        if not bets:
            return {
                "user_id": user.id,
                "profile_type": user.risk_profile,
                "risk_score": 0.40 if user.risk_profile == "MODERADO" else 0.20,
                "metrics": {
                    "avg_odd": 0.0,
                    "median_odd": 0.0,
                    "avg_stake": 0.0,
                    "stake_volatility": 0.0,
                    "high_odd_ratio": 0.0,
                },
            }

        odds = [float(b.odd_taken) for b in bets]
        stakes = [float(b.stake) for b in bets]

        avg_odd = sum(odds) / len(odds)
        median_odd = median(odds)
        avg_stake = sum(stakes) / len(stakes)
        high_odd_ratio = sum(1 for x in odds if x >= 2.8) / len(odds)

        if len(stakes) > 1 and avg_stake > 0:
            variance = sum((s - avg_stake) ** 2 for s in stakes) / len(stakes)
            stake_volatility = (variance ** 0.5) / avg_stake
        else:
            stake_volatility = 0.0

        risk_score = 0.0

        if avg_odd > 2.8:
            risk_score += 0.5
        elif avg_odd > 1.8:
            risk_score += 0.25

        if high_odd_ratio > 0.4:
            risk_score += 0.3
        elif high_odd_ratio > 0.2:
            risk_score += 0.15

        if stake_volatility > 0.5:
            risk_score += 0.2
        elif stake_volatility > 0.25:
            risk_score += 0.1

        if risk_score >= 0.65:
            profile_type = "RISCO"
        elif risk_score >= 0.35:
            profile_type = "MODERADO"
        else:
            profile_type = "SAFE"

        user.risk_profile = profile_type
        self.db.commit()

        return {
            "user_id": user.id,
            "profile_type": profile_type,
            "risk_score": round(risk_score, 4),
            "metrics": {
                "avg_odd": round(avg_odd, 4),
                "median_odd": round(median_odd, 4),
                "avg_stake": round(avg_stake, 2),
                "stake_volatility": round(stake_volatility, 4),
                "high_odd_ratio": round(high_odd_ratio, 4),
            },
        }