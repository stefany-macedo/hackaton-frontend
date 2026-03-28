from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import psycopg
from psycopg.rows import dict_row

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

PREGAME_MODEL_PATH = PROJECT_DIR / "artifacts" / "match_result_model_v2" / "model.joblib"
PREGAME_FEATURE_COLUMNS_PATH = PROJECT_DIR / "artifacts" / "match_result_model_v2" / "feature_columns.json"
BOOKMAKER_MARGIN = 0.06


def get_database_url() -> str:
    database_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if database_url:
        return database_url

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


def resolve_pregame_table_name(conn: psycopg.Connection) -> str:
    candidates = [
        "public.match_pre_game_features",
        "match_pre_game_features",
    ]

    with conn.cursor() as cur:
        for table_name in candidates:
            cur.execute(
                "SELECT to_regclass(%s) AS regclass_name",
                (table_name,),
            )
            row = cur.fetchone()

            if row and row["regclass_name"]:
                return table_name

    raise ValueError(
        "Tabela de features pré-jogo não encontrada. "
        "Esperado um destes nomes: "
        "public.match_pre_game_features ou match_pre_game_features."
    )


@dataclass
class PreGameOddsService:
    model_path: Path = PREGAME_MODEL_PATH
    feature_columns_path: Path = PREGAME_FEATURE_COLUMNS_PATH
    bookmaker_margin: float = BOOKMAKER_MARGIN

    def __post_init__(self) -> None:
        self.database_url = get_database_url()

        print(f"[PreGameOddsService] PROJECT_DIR={PROJECT_DIR}")
        print(f"[PreGameOddsService] model_path={self.model_path}")
        print(f"[PreGameOddsService] model_exists={self.model_path.exists()}")
        print(f"[PreGameOddsService] feature_columns_path={self.feature_columns_path}")
        print(f"[PreGameOddsService] feature_columns_exists={self.feature_columns_path.exists()}")

        if not self.model_path.exists():
            raise FileNotFoundError(f"Modelo pré-jogo não encontrado em: {self.model_path}")

        if not self.feature_columns_path.exists():
            raise FileNotFoundError(
                f"Arquivo de colunas de features não encontrado em: {self.feature_columns_path}"
            )

        self.model = joblib.load(self.model_path)

        with open(self.feature_columns_path, "r", encoding="utf-8") as f:
            self.feature_columns: list[str] = json.load(f)

        if not isinstance(self.feature_columns, list) or not self.feature_columns:
            raise ValueError(
                f"Arquivo de features inválido em {self.feature_columns_path}. "
                "Esperado: lista JSON com nomes de colunas."
            )

    def get_match_probabilities(self, source_match_id: int) -> dict[str, float]:
        features = self._fetch_features(source_match_id)

        X = pd.DataFrame([features])

        missing_cols = [col for col in self.feature_columns if col not in X.columns]
        if missing_cols:
            print(
                f"[WARN] Colunas ausentes para source_match_id={source_match_id}. "
                f"Preenchendo com 0.0: {missing_cols}"
            )
            for col in missing_cols:
                X[col] = 0.0

        X = X[self.feature_columns].copy()

        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors="coerce")

        null_cols = X.columns[X.isnull().any()].tolist()
        if null_cols:
            print(
                f"[WARN] Nulos encontrados nas features pré-jogo para "
                f"source_match_id={source_match_id}. Preenchendo com 0.0: {null_cols}"
            )
            X = X.fillna(0.0)

        X = X.astype("float32")
        proba = self.model.predict_proba(X)[0]

        return {
            "H": float(proba[0]),
            "D": float(proba[1]),
            "A": float(proba[2]),
        }

    def get_main_market_odds(self, source_match_id: int) -> dict[str, Any]:
        probs = self.get_match_probabilities(source_match_id)

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
        home_team: str,
        away_team: str,
    ) -> list[dict[str, Any]]:
        probs = self.get_match_probabilities(source_match_id)

        fair_home = self._prob_to_fair_odd(probs["H"])
        fair_draw = self._prob_to_fair_odd(probs["D"])
        fair_away = self._prob_to_fair_odd(probs["A"])

        market_home = self._fair_to_market_odd(fair_home)
        market_draw = self._fair_to_market_odd(fair_draw)
        market_away = self._fair_to_market_odd(fair_away)

        p_home_draw = min(probs["H"] + probs["D"], 0.999999)
        fair_home_draw = self._prob_to_fair_odd(p_home_draw)
        market_home_draw = self._fair_to_market_odd(fair_home_draw)

        p_over_2_5_goals = max(0.20, min(0.80, 0.35 + 0.25 * probs["H"] + 0.20 * probs["A"]))
        fair_over_2_5_goals = self._prob_to_fair_odd(p_over_2_5_goals)
        market_over_2_5_goals = self._fair_to_market_odd(fair_over_2_5_goals)

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
                        "risk_level": "medio",
                    }
                ],
            },
        ]

    def _fetch_features(self, source_match_id: int) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            table_name = resolve_pregame_table_name(conn)

            query = f"""
            SELECT *
            FROM {table_name}
            WHERE match_id = %s
            LIMIT 1;
            """

            with conn.cursor() as cur:
                cur.execute(query, (source_match_id,))
                row = cur.fetchone()

        if not row:
            raise ValueError(
                f"Features pré-jogo não encontradas para source_match_id={source_match_id}"
            )

        data = dict(row)

        for key, value in list(data.items()):
            if value is None:
                data[key] = 0.0
            elif isinstance(value, (int, float)):
                data[key] = float(value)

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