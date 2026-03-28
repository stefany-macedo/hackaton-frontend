from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row


# ===== BANCO ORIGEM (LOCAL) =====
SOURCE_CONFIG = {
    "dbname": "ml_futebol",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": 53432,
    "sslmode": "prefer",
}

# ===== BANCO DESTINO (SUPABASE) =====

LIMIT_MATCHES = 10


def make_conn(config):
    return psycopg.connect(**config, row_factory=dict_row)


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


# =========================
# DESCOBRIR 10 JOGOS
# =========================

def fetch_match_ids(limit_matches: int = LIMIT_MATCHES) -> list[int]:
    query = """
    SELECT m.match_id
    FROM silver.matches m
    WHERE EXTRACT(YEAR FROM m.match_date) = 2016
    ORDER BY m.match_date, m.match_id
    LIMIT %s;
    """

    with make_conn(SOURCE_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (limit_matches,))
            rows = cur.fetchall()

    return [int(row["match_id"]) for row in rows]


# =========================
# VERIFICAÇÕES
# =========================

def assert_source_tables_exist() -> None:
    queries = [
        "SELECT to_regclass('feature_store.match_pre_game_features') AS tbl;",
        "SELECT to_regclass('feature_store.match_in_game_features') AS tbl;",
    ]

    with make_conn(SOURCE_CONFIG) as conn:
        with conn.cursor() as cur:
            for q in queries:
                cur.execute(q)
                row = cur.fetchone()
                if not row or not row["tbl"]:
                    raise RuntimeError(
                        "Tabela de features não encontrada no banco local. "
                        "Verifique se feature_store.match_pre_game_features e "
                        "feature_store.match_in_game_features existem."
                    )


def fetch_table_columns(schema_name: str, table_name: str) -> list[dict]:
    query = """
    SELECT
        column_name,
        data_type,
        is_nullable,
        udt_name,
        ordinal_position
    FROM information_schema.columns
    WHERE table_schema = %s
      AND table_name = %s
    ORDER BY ordinal_position;
    """

    with make_conn(SOURCE_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (schema_name, table_name))
            return [dict(row) for row in cur.fetchall()]


def build_target_create_table_sql(
    target_schema: str,
    target_table: str,
    source_columns: list[dict],
    primary_key_columns: list[str],
) -> str:
    if not source_columns:
        raise ValueError(f"Nenhuma coluna encontrada para {target_schema}.{target_table}")

    lines: list[str] = []
    for col in source_columns:
        col_name = quote_ident(col["column_name"])
        data_type = col["data_type"]
        udt_name = col["udt_name"]
        is_nullable = col["is_nullable"] == "YES"

        if data_type == "ARRAY":
            pg_type = f"{udt_name}[]"
        elif data_type == "USER-DEFINED":
            pg_type = udt_name
        else:
            pg_type = data_type.upper()

        nullable_sql = "" if is_nullable else " NOT NULL"
        lines.append(f"    {col_name} {pg_type}{nullable_sql}")

    pk_sql = ", ".join(quote_ident(c) for c in primary_key_columns)

    sql = f"""
    CREATE TABLE IF NOT EXISTS {quote_ident(target_schema)}.{quote_ident(target_table)} (
{",\n".join(lines)},
        PRIMARY KEY ({pk_sql})
    );
    """
    return sql


def create_target_tables() -> None:
    pregame_columns = fetch_table_columns("feature_store", "match_pre_game_features")
    ingame_columns = fetch_table_columns("feature_store", "match_in_game_features")

    pregame_sql = build_target_create_table_sql(
        target_schema="public",
        target_table="match_pre_game_features",
        source_columns=pregame_columns,
        primary_key_columns=["match_id"],
    )

    ingame_sql = build_target_create_table_sql(
        target_schema="public",
        target_table="match_in_game_features",
        source_columns=ingame_columns,
        primary_key_columns=["match_id", "minute"],
    )

    with make_conn(TARGET_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(pregame_sql)
            cur.execute(ingame_sql)
        conn.commit()


# =========================
# FETCH DADOS DA ORIGEM
# =========================

def fetch_pregame_rows(match_ids: list[int]) -> list[dict]:
    query = """
    SELECT *
    FROM feature_store.match_pre_game_features
    WHERE match_id = ANY(%s)
    ORDER BY match_id;
    """

    with make_conn(SOURCE_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (match_ids,))
            return [dict(row) for row in cur.fetchall()]


def fetch_ingame_rows(match_ids: list[int]) -> list[dict]:
    query = """
    SELECT *
    FROM feature_store.match_in_game_features
    WHERE match_id = ANY(%s)
    ORDER BY match_id, minute;
    """

    with make_conn(SOURCE_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (match_ids,))
            return [dict(row) for row in cur.fetchall()]


# =========================
# LIMPEZA NO DESTINO
# =========================

def clear_target_rows(match_ids: list[int]) -> None:
    with make_conn(TARGET_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM public.match_in_game_features WHERE match_id = ANY(%s);",
                (match_ids,),
            )
            cur.execute(
                "DELETE FROM public.match_pre_game_features WHERE match_id = ANY(%s);",
                (match_ids,),
            )
        conn.commit()


# =========================
# UPSERT DINÂMICO
# =========================

def upsert_rows(
    conn: psycopg.Connection,
    table_name: str,
    rows: list[dict],
    conflict_columns: list[str],
) -> None:
    if not rows:
        return

    columns = list(rows[0].keys())
    insert_columns_sql = ", ".join(quote_ident(col) for col in columns)
    values_sql = ", ".join(["%s"] * len(columns))
    conflict_sql = ", ".join(quote_ident(col) for col in conflict_columns)

    update_columns = [col for col in columns if col not in conflict_columns]
    update_sql = ", ".join(
        f"{quote_ident(col)} = EXCLUDED.{quote_ident(col)}"
        for col in update_columns
    )

    query = f"""
    INSERT INTO {table_name} ({insert_columns_sql})
    VALUES ({values_sql})
    ON CONFLICT ({conflict_sql})
    DO UPDATE SET {update_sql};
    """

    with conn.cursor() as cur:
        for row in rows:
            values = [normalize_value(row[col]) for col in columns]
            cur.execute(query, values)


# =========================
# VALIDAÇÃO
# =========================

def validate_target_counts(match_ids: list[int]) -> None:
    with make_conn(TARGET_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM public.match_pre_game_features WHERE match_id = ANY(%s);",
                (match_ids,),
            )
            pregame_count = cur.fetchone()["total"]

            cur.execute(
                "SELECT COUNT(*) AS total FROM public.match_in_game_features WHERE match_id = ANY(%s);",
                (match_ids,),
            )
            ingame_count = cur.fetchone()["total"]

    print(f"Pregame no destino: {pregame_count}")
    print(f"Ingame no destino: {ingame_count}")


# =========================
# MAIN
# =========================

def main() -> None:
    print("Verificando tabelas de origem...")
    assert_source_tables_exist()

    print("Buscando 10 match_ids...")
    match_ids = fetch_match_ids(LIMIT_MATCHES)
    print("Match IDs:", match_ids)

    if not match_ids:
        raise RuntimeError("Nenhum match_id encontrado para migração.")

    print("Criando tabelas no Supabase, se necessário...")
    create_target_tables()

    print("Limpando dados antigos desses 10 jogos no destino...")
    clear_target_rows(match_ids)

    print("Buscando rows pré-jogo...")
    pregame_rows = fetch_pregame_rows(match_ids)
    print(f"Pregame rows encontradas: {len(pregame_rows)}")

    print("Buscando rows in-game...")
    ingame_rows = fetch_ingame_rows(match_ids)
    print(f"Ingame rows encontradas: {len(ingame_rows)}")

    with make_conn(TARGET_CONFIG) as conn:
        print("Inserindo/upsert pregame...")
        upsert_rows(
            conn=conn,
            table_name="public.match_pre_game_features",
            rows=pregame_rows,
            conflict_columns=["match_id"],
        )

        print("Inserindo/upsert ingame...")
        upsert_rows(
            conn=conn,
            table_name="public.match_in_game_features",
            rows=ingame_rows,
            conflict_columns=["match_id", "minute"],
        )

        conn.commit()

    print("Validando contagens no destino...")
    validate_target_counts(match_ids)

    print("✅ Migração das features concluída com sucesso!")


if __name__ == "__main__":
    main()