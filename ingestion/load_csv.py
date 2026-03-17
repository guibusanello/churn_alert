"""
ingestion/load_csv.py
─────────────────────
Script de ingestão dos CSVs para o Supabase (PostgreSQL).
Executa validação, upsert idempotente e logging estruturado.

Dependências:
    pip install psycopg2-binary pandas python-dotenv

Variáveis de ambiente (.env):
    SUPABASE_HOST
    SUPABASE_PORT      (padrão: 5432)
    SUPABASE_DB        (padrão: postgres)
    SUPABASE_USER
    SUPABASE_PASSWORD
"""

import os
import logging
import time
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Configuração das tabelas ─────────────────────────────────────────────────

@dataclass
class TableConfig:
    csv_file:      str
    table_name:    str
    primary_key:   str
    nullable_cols: list[str] = field(default_factory=list)
    bool_cols:     list[str] = field(default_factory=list)
    date_cols:     list[str] = field(default_factory=list)
    int_cols:      list[str] = field(default_factory=list)


TABLES: list[TableConfig] = [
    TableConfig(
        csv_file    = "crm_accounts.csv",
        table_name  = "crm_accounts",
        primary_key = "account_id",
        nullable_cols = ["nps_score", "last_qbr_date"],
        date_cols   = ["created_date", "last_qbr_date"],
        int_cols    = ["employee_count", "mrr", "health_score", "nps_score"],
    ),
    TableConfig(
        csv_file    = "crm_contracts.csv",
        table_name  = "crm_contracts",
        primary_key = "contract_id",
        bool_cols   = ["auto_renew"],
        date_cols   = ["start_date", "end_date"],
        int_cols    = ["arr"],
    ),
    TableConfig(
        csv_file    = "user_activity_events.csv",
        table_name  = "user_activity_events",
        primary_key = "event_id",
        date_cols   = ["event_date"],
        int_cols    = ["duration_sec"],
    ),
    TableConfig(
        csv_file    = "support_tickets.csv",
        table_name  = "support_tickets",
        primary_key = "ticket_id",
        nullable_cols = ["resolved_date", "resolution_days", "satisfaction"],
        bool_cols   = ["reopened"],
        date_cols   = ["created_date", "resolved_date"],
        int_cols    = ["org_id", "resolution_days", "satisfaction"],
    ),
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_connection() -> psycopg2.extensions.connection:
    """Cria conexão com o Supabase usando variáveis de ambiente."""
    load_dotenv()
    conn = psycopg2.connect(
        host            = os.environ["SUPABASE_HOST"],
        port            = int(os.environ.get("SUPABASE_PORT", 5432)),
        dbname          = os.environ.get("SUPABASE_DB", "postgres"),
        user            = os.environ["SUPABASE_USER"],
        password        = os.environ["SUPABASE_PASSWORD"],
        sslmode         = "require",
        connect_timeout = 10,
    )
    conn.autocommit = False
    return conn


def _sanitize(val):
    """
    Converte tipos numpy/pandas para Python nativo antes de passar ao psycopg2.
    Sem isso, numpy.int64 causa 'integer out of range' no driver.
    """
    if val is None:
        return None
    if isinstance(val, float) and np.isnan(val):
        return None
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val


def validate_file(path: Path, config: TableConfig) -> pd.DataFrame:
    """
    Lê o CSV, aplica tipagem e valida presença do primary key.
    Retorna o DataFrame limpo ou lança exceção.
    """
    log.info(f"  Lendo {path.name} ...")
    df = pd.read_csv(path, dtype=str)   # lê tudo como string primeiro

    # Primary key não pode ser nulo nem duplicado
    if df[config.primary_key].isnull().any():
        raise ValueError(f"Primary key '{config.primary_key}' contém valores nulos em {path.name}")

    if df[config.primary_key].duplicated().any():
        n_dup = df[config.primary_key].duplicated().sum()
        raise ValueError(f"Primary key '{config.primary_key}' tem {n_dup} duplicatas em {path.name}")

    # Converter colunas booleanas
    for col in config.bool_cols:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False, "true": True, "false": False})

    # Converter colunas de data (string vazia → NaT → None)
    for col in config.date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    # Converter colunas inteiras (string vazia → NaN → None)
    for col in config.int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Substituir NaN / strings vazias por None (NULL no Postgres)
    df = df.where(pd.notnull(df), None)
    df = df.map(lambda x: None if x == "" else x)

    log.info(f"  ✓ {len(df)} linhas validadas")
    return df


def upsert_table(
    conn:       psycopg2.extensions.connection,
    df:         pd.DataFrame,
    config:     TableConfig,
    batch_size: int = 500,
) -> int:
    """
    Faz upsert idempotente usando INSERT ... ON CONFLICT DO UPDATE.
    Retorna total de linhas inseridas/atualizadas.
    """
    columns     = list(df.columns)
    pk          = config.primary_key
    update_cols = [c for c in columns if c != pk]

    cols_str   = ", ".join(columns)
    update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    query = f"""
        INSERT INTO {config.table_name} ({cols_str})
        VALUES %s
        ON CONFLICT ({pk}) DO UPDATE SET {update_str}
    """

    # _sanitize converte numpy int64/float64/bool_ para tipos Python nativos
    # evitando o erro "integer out of range" no psycopg2
    records = [
        tuple(_sanitize(v) for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    total = 0
    with conn.cursor() as cur:
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            execute_values(cur, query, batch)
            total += len(batch)
            log.info(f"    → {total}/{len(records)} linhas processadas")

    return total


def refresh_materialized_views(conn: psycopg2.extensions.connection) -> None:
    """
    Atualiza todas as materialized views após a ingestão.
    Ordem obrigatória: silver primeiro (crm_accounts antes das demais,
    pois user_activity e support_tickets dependem dela), gold por último.
    """
    views = [
        "silver.crm_accounts",           # base da identity resolution
        "silver.crm_contracts",
        "silver.user_activity_events",   # depende de silver.crm_accounts
        "silver.support_tickets",        # depende de silver.crm_accounts
        "gold.churn_score",              # depende de todas as silver
    ]

    for view in views:
        try:
            log.info(f"  Atualizando {view} ...")
            with conn.cursor() as cur:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view};")
            conn.commit()
            log.info(f"  ✓ {view} atualizada")
        except Exception as exc:
            conn.rollback()
            if "does not exist" in str(exc):
                log.warning(
                    f"  {view} ainda não existe — execute o medallion_ddl.sql primeiro."
                )
            else:
                log.warning(f"  Não foi possível atualizar {view}: {exc}")


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run(data_dir: str = "data") -> None:
    base_path = Path(data_dir)

    log.info("=" * 55)
    log.info("  Iniciando pipeline de ingestão")
    log.info("=" * 55)

    conn: Optional[psycopg2.extensions.connection] = None
    start_total = time.perf_counter()

    try:
        conn = get_connection()
        log.info("✓ Conexão com Supabase estabelecida\n")

        summary: list[dict] = []

        for config in TABLES:
            path = base_path / config.csv_file
            log.info(f"┌─ {config.table_name}")

            if not path.exists():
                log.warning(f"  Arquivo não encontrado: {path} — pulando")
                continue

            t0 = time.perf_counter()

            try:
                df      = validate_file(path, config)
                total   = upsert_table(conn, df, config)
                conn.commit()
                elapsed = round(time.perf_counter() - t0, 2)
                log.info(f"└─ ✓ {total} linhas em {elapsed}s\n")
                summary.append({"table": config.table_name, "rows": total, "status": "ok"})

            except Exception as exc:
                conn.rollback()
                log.error(f"└─ ✗ Erro em {config.table_name}: {exc}\n")
                summary.append({"table": config.table_name, "rows": 0, "status": f"erro: {exc}"})

        # Atualiza todas as materialized views silver e gold
        refresh_materialized_views(conn)

        # Resumo final
        elapsed_total = round(time.perf_counter() - start_total, 2)
        log.info("=" * 55)
        log.info(f"  Pipeline concluído em {elapsed_total}s")
        log.info("=" * 55)
        for s in summary:
            icon = "✓" if s["status"] == "ok" else "✗"
            log.info(f"  {icon}  {s['table']:<30} {s['rows']:>6} linhas  [{s['status']}]")
        log.info("=" * 55)

    finally:
        if conn:
            conn.close()
            log.info("\n  Conexão encerrada.")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingestão de CSVs para o Supabase")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Diretório onde estão os CSVs (padrão: ./data)",
    )
    args = parser.parse_args()
    run(data_dir=args.data_dir)
