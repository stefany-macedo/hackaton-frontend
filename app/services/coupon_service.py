from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.recommendation_service import RecommendationService


class CouponService:
    def __init__(self, db: Session):
        self.db = db
        self.recommendation_service = RecommendationService(db)

    def compose_coupon(
        self,
        user_id: str,
        matches: list[str],
        max_selections: int,
        target_risk: str,
    ) -> dict:
        del user_id  # por enquanto não é usado na composição

        all_live_recommendations = self.recommendation_service.get_live_recommendations(
            limit=200
        )

        selected_match_ids = set(matches)
        all_recommendations: list[dict] = []

        for rec in all_live_recommendations:
            rec_match_id = rec.get("id")
            if rec_match_id not in selected_match_ids:
                continue

            normalized_recs = self._expand_match_into_recommendations(rec)
            for item in normalized_recs:
                item["match_id"] = rec_match_id
                all_recommendations.append(item)

        filtered = self._filter_by_target_risk(all_recommendations, target_risk)
        ranked = sorted(
            filtered,
            key=lambda x: x.get("recommendation_score", 0),
            reverse=True,
        )

        selected = ranked[:max_selections]

        total_odd = 1.0
        for item in selected:
            total_odd *= float(item["market_odd"])

        return {
            "user_profile": target_risk,
            "coupon": {
                "selections": selected,
                "total_odd": round(total_odd, 2),
                "overall_risk": target_risk.lower(),
                "assistant_text": self._coupon_text(target_risk, selected, total_odd),
            },
        }

    def _expand_match_into_recommendations(self, match_data: dict) -> list[dict]:
        """
        Converte a resposta simplificada de /games/live em recomendações utilizáveis
        para múltipla.
        """
        team1 = match_data.get("team1", "Mandante")
        team2 = match_data.get("team2", "Visitante")

        options = [
            {
                "market_type": "1x2",
                "selection_key": "home",
                "selection_label": f"{team1} vence",
                "market_odd": float(match_data["o1"]),
                "risk_level": "medio",
            },
            {
                "market_type": "1x2",
                "selection_key": "draw",
                "selection_label": "Empate",
                "market_odd": float(match_data["ox"]),
                "risk_level": "baixo",
            },
            {
                "market_type": "1x2",
                "selection_key": "away",
                "selection_label": f"{team2} vence",
                "market_odd": float(match_data["o2"]),
                "risk_level": "alto",
            },
        ]

        for item in options:
            odd = float(item["market_odd"])
            item["recommendation_score"] = round(1 / odd, 6) if odd > 0 else 0.0

        return options

    def _filter_by_target_risk(self, recs: list[dict], target_risk: str) -> list[dict]:
        if target_risk == "SAFE":
            return [r for r in recs if r["risk_level"] == "baixo"]
        if target_risk == "MODERADO":
            return [r for r in recs if r["risk_level"] in {"baixo", "medio"}]
        return recs

    def _coupon_text(self, target_risk: str, selected: list[dict], total_odd: float) -> str:
        if not selected:
            return "Não encontrei uma múltipla adequada para esse perfil agora."

        return (
            f"Montei uma múltipla para perfil {target_risk.lower()}, com "
            f"{len(selected)} seleção(ões) e odd total de {round(total_odd, 2)}."
        )