from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import psycopg
from psycopg.rows import dict_row


PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
INPLAY_MODEL_PATH = PROJECT_DIR / "artifacts" / "inplay_xgb_model.pkl"
INPLAY_FEATURE_COLUMNS_PATH = PROJECT_DIR / "artifacts" / "inplay_feature_columns.pkl"
BOOKMAKER_MARGIN = 0.06


def get_database_url() -> str:
   # database_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
  #  if database_url:
     #   return database_url

    dbname = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT", "5432")
    sslmode = os.getenv("POSTGRES_SSLMODE", "require")

    if not all([dbname, user, password, host]):
        raise ValueError(
            "Variáveis de ambiente do banco não encontradas. "
            "Defina SUPABASE_DB_URL ou DATABASE_URL, "
            "ou então POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, "
            "POSTGRES_HOST, POSTGRES_PORT e POSTGRES_SSLMODE."
        )

    return (
        f"dbname={dbname} "
        f"user={user} "
        f"password={password} "
        f"host={host} "
        f"port={port} "
        f"sslmode={sslmode}"
    )


@dataclass
class InPlayModelOddsService:
    model_path: Path = Path(INPLAY_MODEL_PATH)
    feature_columns_path: Path = Path(INPLAY_FEATURE_COLUMNS_PATH)
    bookmaker_margin: float = BOOKMAKER_MARGIN

    def __post_init__(self) -> None:
        self.model = joblib.load(self.model_path)
        self.feature_columns: list[str] = joblib.load(self.feature_columns_path)
        self.database_url = get_database_url()

    def get_match_probabilities(self, source_match_id: int, minute: int) -> dict[str, float]:
        features = self._fetch_features(source_match_id=source_match_id, minute=minute)
        features = self._add_derived_features(features)

        X = pd.DataFrame([features])
        X = X[self.feature_columns].copy()

        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors="coerce")

        null_cols = X.columns[X.isnull().any()].tolist()
        if null_cols:
            raise ValueError(f"Nulos encontrados nas features in-play: {null_cols}")

        X = X.astype("float32")
        proba = self.model.predict_proba(X)[0]

        return {
            "H": float(proba[0]),
            "D": float(proba[1]),
            "A": float(proba[2]),
        }

    def get_main_market_odds(self, source_match_id: int, minute: int) -> dict[str, Any]:
        probs = self.get_match_probabilities(source_match_id, minute)

        fair_home = self._prob_to_fair_odd(probs["H"])
        fair_draw = self._prob_to_fair_odd(probs["D"])
        fair_away = self._prob_to_fair_odd(probs["A"])

        return {
            "probabilities": probs,
            "fair_odds": {"H": fair_home, "D": fair_draw, "A": fair_away},
            "market_odds": {
                "H": self._fair_to_market_odd(fair_home),
                "D": self._fair_to_market_odd(fair_draw),
                "A": self._fair_to_market_odd(fair_away),
            },
        }

    def build_markets_from_model(
        self,
        source_match_id: int,
        minute: int,
        home_team: str,
        away_team: str,
    ) -> list[dict[str, Any]]:
        probs = self.get_match_probabilities(source_match_id=source_match_id, minute=minute)
        features = self._add_derived_features(
            self._fetch_features(source_match_id=source_match_id, minute=minute)
        )

        fair_home = self._prob_to_fair_odd(probs["H"])
        fair_draw = self._prob_to_fair_odd(probs["D"])
        fair_away = self._prob_to_fair_odd(probs["A"])

        market_home = self._fair_to_market_odd(fair_home)
        market_draw = self._fair_to_market_odd(fair_draw)
        market_away = self._fair_to_market_odd(fair_away)

        p_home_draw = min(probs["H"] + probs["D"], 0.999999)
        fair_home_draw = self._prob_to_fair_odd(p_home_draw)
        market_home_draw = self._fair_to_market_odd(fair_home_draw)

        home_sot = float(features["home_shots_on_target_cum"])
        away_sot = float(features["away_shots_on_target_cum"])
        total_sot_now = home_sot + away_sot

        home_shots = float(features["home_shots_cum"])
        away_shots = float(features["away_shots_cum"])
        total_shots_now = home_shots + away_shots

        home_goals = float(features["home_score_now"])
        away_goals = float(features["away_score_now"])
        total_goals_now = home_goals + away_goals

        goal_diff_now = float(features["goal_diff_now"])
        remaining_minutes = float(features["remaining_minutes"])

        sot_diff = home_sot - away_sot
        p_home_sot = max(0.15, min(0.85, 0.50 + 0.06 * sot_diff + 0.04 * goal_diff_now))
        fair_home_sot = self._prob_to_fair_odd(p_home_sot)
        market_home_sot = self._fair_to_market_odd(fair_home_sot)

        total_xg_now = float(features["home_xg_cum"]) + float(features["away_xg_cum"])
        goals_pace = total_goals_now / max(minute, 1)
        xg_pace = total_xg_now / max(minute, 1)

        expected_additional_goals = (
            goals_pace * remaining_minutes * 0.55
            + xg_pace * remaining_minutes * 0.90
        )
        expected_final_goals = total_goals_now + expected_additional_goals

        if total_goals_now >= 3:
            p_over_2_5_goals = 0.999
        else:
            p_over_2_5_goals = self._clip_prob(self._sigmoid(expected_final_goals - 2.5, 1.35))

        fair_over_2_5_goals = self._prob_to_fair_odd(p_over_2_5_goals)
        market_over_2_5_goals = self._fair_to_market_odd(fair_over_2_5_goals)

        shots_pace = total_shots_now / max(minute, 1)
        recent_shots = float(features["home_shots_last_10"]) + float(features["away_shots_last_10"])
        expected_additional_shots = (
            shots_pace * remaining_minutes * 0.70
            + (recent_shots / 10.0) * remaining_minutes * 0.45
        )
        expected_final_shots = total_shots_now + expected_additional_shots

        if total_shots_now >= 9:
            p_over_8_5_shots = 0.999
        else:
            p_over_8_5_shots = self._clip_prob(self._sigmoid(expected_final_shots - 8.5, 0.85))

        fair_over_8_5_shots = self._prob_to_fair_odd(p_over_8_5_shots)
        market_over_8_5_shots = self._fair_to_market_odd(fair_over_8_5_shots)

        sot_pace = total_sot_now / max(minute, 1)
        recent_sot = float(features["home_shots_on_target_last_10"]) + float(features["away_shots_on_target_last_10"])
        expected_additional_sot = (
            sot_pace * remaining_minutes * 0.75
            + (recent_sot / 10.0) * remaining_minutes * 0.55
        )
        expected_final_sot = total_sot_now + expected_additional_sot

        if total_sot_now >= 5:
            p_over_4_5_sot = 0.999
        else:
            p_over_4_5_sot = self._clip_prob(self._sigmoid(expected_final_sot - 4.5, 1.05))

        fair_over_4_5_sot = self._prob_to_fair_odd(p_over_4_5_sot)
        market_over_4_5_sot = self._fair_to_market_odd(fair_over_4_5_sot)

        return [
            {
                "market_type": "1x2",
                "market_name": "Resultado Final",
                "options": [
                    {
                        "selection_key": "home",
                        "selection_label": f"{home_team} vence",
                        "market_odd": market_home,
                        "model_odd": fair_home,
                        "model_probability": round(probs["H"], 6),
                        "edge_pct": self._edge_pct(fair_home, market_home),
                        "risk_level": "medio",
                    },
                    {
                        "selection_key": "draw",
                        "selection_label": "Empate",
                        "market_odd": market_draw,
                        "model_odd": fair_draw,
                        "model_probability": round(probs["D"], 6),
                        "edge_pct": self._edge_pct(fair_draw, market_draw),
                        "risk_level": "medio",
                    },
                    {
                        "selection_key": "away",
                        "selection_label": f"{away_team} vence",
                        "market_odd": market_away,
                        "model_odd": fair_away,
                        "model_probability": round(probs["A"], 6),
                        "edge_pct": self._edge_pct(fair_away, market_away),
                        "risk_level": "alto",
                    },
                ],
            },
            {
                "market_type": "double_chance",
                "market_name": "Dupla Chance",
                "options": [
                    {
                        "selection_key": "home_draw",
                        "selection_label": f"{home_team} ou empate",
                        "market_odd": market_home_draw,
                        "model_odd": fair_home_draw,
                        "model_probability": round(p_home_draw, 6),
                        "edge_pct": self._edge_pct(fair_home_draw, market_home_draw),
                        "risk_level": "baixo",
                    }
                ],
            },
            {
                "market_type": "shots_on_target_team",
                "market_name": "Equipe com Mais Chutes no Gol",
                "options": [
                    {
                        "selection_key": "home_sot",
                        "selection_label": f"{home_team} com mais chutes no gol",
                        "market_odd": market_home_sot,
                        "model_odd": fair_home_sot,
                        "model_probability": round(p_home_sot, 6),
                        "edge_pct": self._edge_pct(fair_home_sot, market_home_sot),
                        "risk_level": "alto" if p_home_sot < 0.58 else "medio",
                    }
                ],
            },
            {
                "market_type": "total_goals",
                "market_name": "Total de Gols",
                "options": [
                    {
                        "selection_key": "over_2_5_goals",
                        "selection_label": "Mais de 2.5 gols",
                        "market_odd": market_over_2_5_goals,
                        "model_odd": fair_over_2_5_goals,
                        "model_probability": round(p_over_2_5_goals, 6),
                        "edge_pct": self._edge_pct(fair_over_2_5_goals, market_over_2_5_goals),
                        "risk_level": "medio" if p_over_2_5_goals >= 0.50 else "alto",
                    }
                ],
            },
            {
                "market_type": "total_shots",
                "market_name": "Total de Finalizações",
                "options": [
                    {
                        "selection_key": "over_8_5_shots",
                        "selection_label": "Mais de 8.5 finalizações",
                        "market_odd": market_over_8_5_shots,
                        "model_odd": fair_over_8_5_shots,
                        "model_probability": round(p_over_8_5_shots, 6),
                        "edge_pct": self._edge_pct(fair_over_8_5_shots, market_over_8_5_shots),
                        "risk_level": "baixo" if p_over_8_5_shots >= 0.62 else "medio",
                    }
                ],
            },
            {
                "market_type": "total_shots_on_target",
                "market_name": "Total de Chutes no Gol",
                "options": [
                    {
                        "selection_key": "over_4_5_sot",
                        "selection_label": "Mais de 4.5 chutes no gol",
                        "market_odd": market_over_4_5_sot,
                        "model_odd": fair_over_4_5_sot,
                        "model_probability": round(p_over_4_5_sot, 6),
                        "edge_pct": self._edge_pct(fair_over_4_5_sot, market_over_4_5_sot),
                        "risk_level": "baixo" if p_over_4_5_sot >= 0.60 else "medio",
                    }
                ],
            },
        ]

    def _fetch_features(self, source_match_id: int, minute: int) -> dict[str, Any]:
        query = """
        SELECT
            minute,
            home_score_now,
            away_score_now,
            goal_diff_now,
            home_shots_cum,
            away_shots_cum,
            home_shots_on_target_cum,
            away_shots_on_target_cum,
            home_xg_cum,
            away_xg_cum,
            home_shots_last_10,
            away_shots_last_10,
            home_shots_on_target_last_10,
            away_shots_on_target_last_10,
            home_xg_last_10,
            away_xg_last_10,
            home_red_cards,
            away_red_cards,
            home_fouls_cum,
            away_fouls_cum,
            home_passes_cum,
            away_passes_cum,
            diff_shots_cum,
            diff_shots_on_target_cum,
            diff_xg_cum,
            diff_shots_last_10,
            diff_shots_on_target_last_10,
            diff_xg_last_10,
            diff_red_cards,
            diff_fouls_cum,
            diff_passes_cum,
            remaining_minutes
        FROM public.match_in_game_features
        WHERE match_id = %s
          AND minute = %s
        LIMIT 1;
        """
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source_match_id, minute))
                row = cur.fetchone()

        if not row:
            raise ValueError(f"Features não encontradas para source_match_id={source_match_id}, minute={minute}")

        data = dict(row)
        for key, value in data.items():
            data[key] = int(value) if key == "minute" else float(value)

        return data

    def _add_derived_features(self, data: dict[str, Any]) -> dict[str, Any]:
        goal_diff_now = float(data["goal_diff_now"])
        minute = int(data["minute"])
        minute_progress = minute / 90.0

        data["is_draw_now"] = int(goal_diff_now == 0)
        data["abs_goal_diff_now"] = abs(goal_diff_now)
        data["minute_progress"] = minute_progress
        data["score_pressure"] = goal_diff_now * minute_progress
        data["late_game_draw"] = int(goal_diff_now == 0 and minute >= 60)
        data["xg_pressure_diff"] = float(data["diff_xg_last_10"]) * minute_progress
        data["shots_pressure_diff"] = float(data["diff_shots_last_10"]) * minute_progress
        data["passes_pressure_diff"] = float(data["diff_passes_cum"]) * minute_progress

        return data

    @staticmethod
    def _prob_to_fair_odd(prob: float) -> float:
        prob = max(min(prob, 0.999999), 0.000001)
        return round(1.0 / prob, 2)

    def _fair_to_market_odd(self, fair_odd: float) -> float:
        fair_prob = 1.0 / fair_odd
        market_prob = fair_prob * (1.0 + self.bookmaker_margin)
        return round(max(1.0 / market_prob, 1.01), 2)

    @staticmethod
    def _edge_pct(model_fair_odd: float, market_odd: float) -> float:
        return round(((market_odd - model_fair_odd) / market_odd) * 100.0, 4)

    @staticmethod
    def _clip_prob(prob: float) -> float:
        return max(0.02, min(0.98, prob))

    @staticmethod
    def _sigmoid(x: float, scale: float = 1.0) -> float:
        import math
        return 1.0 / (1.0 + math.exp(-x * scale))