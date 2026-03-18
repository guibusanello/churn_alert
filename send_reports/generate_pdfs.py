"""
alerts/generate_pdfs.py
───────────────────────
Gera os PDFs de churn alert localmente sem enviar e-mails.
Útil para validar o layout com dados reais antes de disparar os alertas.

Uso:
    python alerts/generate_pdfs.py
    python alerts/generate_pdfs.py --output-dir relatorios/

Saída:
    churn_resumo_geral_YYYYMMDD.pdf
    churn_<owner>_YYYYMMDD.pdf  (um por CS owner)

Dependências:
    pip install psycopg2-binary pandas python-dotenv reportlab

Variáveis de ambiente (.env):
    SUPABASE_HOST, SUPABASE_PORT, SUPABASE_DB
    SUPABASE_USER, SUPABASE_PASSWORD
"""

import os
import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# Importa as funções de geração de PDF do send_alerts.py
# Ambos os scripts devem estar na mesma pasta alerts/
import sys
sys.path.insert(0, str(Path(__file__).parent))
from send_alerts import generate_pdf, fmt_mrr, today_str

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_connection() -> psycopg2.extensions.connection:
    load_dotenv()
    return psycopg2.connect(
        host            = os.environ["SUPABASE_HOST"],
        port            = int(os.environ.get("SUPABASE_PORT", 5432)),
        dbname          = os.environ.get("SUPABASE_DB", "postgres"),
        user            = os.environ["SUPABASE_USER"],
        password        = os.environ["SUPABASE_PASSWORD"],
        sslmode         = "require",
        connect_timeout = 10,
    )


def fetch_churn_score() -> list[dict]:
    log.info("Buscando dados do gold.churn_score ...")
    conn = get_connection()
    query = """
        SELECT
            risk_rank, account_id, company_name, plan, mrr,
            crm_status, cs_owner, risk_level, churn_score,
            sinal_engajamento, sinal_suporte, sinal_contrato, sinal_crm,
            has_overdue, contract_expiring_soon,
            health_score, nps_score
        FROM gold.churn_score
        ORDER BY risk_rank
    """
    df   = pd.read_sql(query, conn)
    conn.close()
    log.info(f"  ✓ {len(df)} clientes carregados")
    return df.to_dict(orient="records")


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def run(output_dir: str = ".") -> None:
    load_dotenv()
    out  = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_str = date.today().strftime("%Y%m%d")

    log.info("=" * 55)
    log.info("  Gerando PDFs de churn alert")
    log.info("=" * 55)

    data = fetch_churn_score()

    # Resumo do que será gerado
    n_alto    = sum(1 for r in data if r["risk_level"] == "Alto")
    n_medio   = sum(1 for r in data if r["risk_level"] == "Medio")
    n_baixo   = sum(1 for r in data if r["risk_level"] == "Baixo")
    mrr_risco = sum(r["mrr"] for r in data if r["risk_level"] in ("Alto", "Medio"))
    owners    = sorted(set(r["cs_owner"] for r in data if r["cs_owner"]))

    log.info(f"\n  Clientes: {len(data)}  |  Alto: {n_alto}  |  Médio: {n_medio}  |  Baixo: {n_baixo}")
    log.info(f"  MRR em risco: {fmt_mrr(mrr_risco)}")
    log.info(f"  CS Owners: {', '.join(owners)}\n")

    generated = []

    # 1. Resumo geral
    path = out / f"churn_resumo_geral_{date_str}.pdf"
    log.info(f"Gerando resumo geral → {path.name}")
    generate_pdf(data, str(path), owner=None)
    log.info(f"  ✓ {path.name}\n")
    generated.append(path)

    # 2. Carteira individual por CS owner
    for owner in owners:
        owner_rows = [r for r in data if r["cs_owner"] == owner]
        owner_slug = owner.lower().replace(" ", "_")
        path       = out / f"churn_{owner_slug}_{date_str}.pdf"

        log.info(f"Gerando carteira de {owner} ({len(owner_rows)} clientes) → {path.name}")
        generate_pdf(owner_rows, str(path), owner=owner)
        log.info(f"  ✓ {path.name}\n")
        generated.append(path)

    # Resumo final
    log.info("=" * 55)
    log.info(f"  {len(generated)} PDFs gerados em '{out.resolve()}'")
    log.info("=" * 55)
    for p in generated:
        log.info(f"  📄 {p.name}")
    log.info("=" * 55)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera PDFs de churn alert sem enviar e-mails")
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Diretório de saída dos PDFs (padrão: diretório atual)",
    )
    args = parser.parse_args()
    run(output_dir=args.output_dir)
