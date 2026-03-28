from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


class MatchSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_upcoming_matches(self, limit: int | None = None) -> int:
        """
        Sincroniza upcoming_matches a partir de public.match_pre_game_features.
        Só entram jogos que realmente possuem features pré-jogo.
        """
        limit_sql = ""
        params: dict[str, object] = {}

        if limit is not None:
            limit_sql = "LIMIT :limit"
            params["limit"] = limit

        sql = text(f"""
            INSERT INTO upcoming_matches (
                id,
                source_match_id,
                league,
                team1,
                team2,
                kickoff_time,
                status
            )
            SELECT
                'upcoming_' || CAST(match_id AS TEXT) AS id,
                match_id AS source_match_id,
                competition_name AS league,
                home_team_name AS team1,
                away_team_name AS team2,
                CAST(match_date AS TEXT) AS kickoff_time,
                'UPCOMING' AS status
            FROM public.match_pre_game_features
            ORDER BY match_date, match_id
            {limit_sql}
            ON CONFLICT (id)
            DO UPDATE SET
                source_match_id = EXCLUDED.source_match_id,
                league = EXCLUDED.league,
                team1 = EXCLUDED.team1,
                team2 = EXCLUDED.team2,
                kickoff_time = EXCLUDED.kickoff_time,
                status = EXCLUDED.status
        """)

        result = self.db.execute(sql, params)
        self.db.commit()
        return result.rowcount or 0

    def sync_live_matches(self, limit: int | None = None) -> int:
        """
        Sincroniza live_matches a partir da última linha disponível por partida
        em public.match_in_game_features.
        """
        limit_sql = ""
        params: dict[str, object] = {}

        if limit is not None:
            limit_sql = "LIMIT :limit"
            params["limit"] = limit

        sql = text(f"""
            WITH latest_ingame AS (
                SELECT DISTINCT ON (match_id)
                    match_id,
                    minute,
                    competition_name,
                    home_team_name,
                    away_team_name,
                    home_score,
                    away_score
                FROM public.match_in_game_features
                ORDER BY match_id, minute DESC
            )
            INSERT INTO live_matches (
                id,
                source_match_id,
                league,
                team1,
                team2,
                score1,
                score2,
                minute,
                status
            )
            SELECT
                'live_' || CAST(match_id AS TEXT) AS id,
                match_id AS source_match_id,
                competition_name AS league,
                home_team_name AS team1,
                away_team_name AS team2,
                COALESCE(home_score, 0) AS score1,
                COALESCE(away_score, 0) AS score2,
                COALESCE(minute, 0) AS minute,
                'LIVE' AS status
            FROM latest_ingame
            ORDER BY source_match_id
            {limit_sql}
            ON CONFLICT (id)
            DO UPDATE SET
                source_match_id = EXCLUDED.source_match_id,
                league = EXCLUDED.league,
                team1 = EXCLUDED.team1,
                team2 = EXCLUDED.team2,
                score1 = EXCLUDED.score1,
                score2 = EXCLUDED.score2,
                minute = EXCLUDED.minute,
                status = EXCLUDED.status
        """)

        result = self.db.execute(sql, params)
        self.db.commit()
        return result.rowcount or 0

    def sync_all(self, limit_upcoming: int | None = None, limit_live: int | None = None) -> dict[str, int]:
        try:
            upcoming_count = self.sync_upcoming_matches(limit=limit_upcoming)
            live_count = self.sync_live_matches(limit=limit_live)
            return {
                "upcoming_synced": upcoming_count,
                "live_synced": live_count,
            }
        except Exception:
            self.db.rollback()
            raise