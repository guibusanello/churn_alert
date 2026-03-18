"""
alerts/send_alerts.py
─────────────────────
Script de envio de alertas de churn por e-mail via SMTP.

Fluxo:
  1. Lê gold.churn_score do Supabase
  2. Gera PDF de resumo geral e envia para o gestor
  3. Gera PDF individual por CS owner e envia para cada um

Dependências:
    pip install psycopg2-binary pandas python-dotenv reportlab

Variáveis de ambiente (.env):
    SUPABASE_HOST, SUPABASE_PORT, SUPABASE_DB
    SUPABASE_USER, SUPABASE_PASSWORD

    SMTP_HOST          (ex: smtp.gmail.com)
    SMTP_PORT          (ex: 587)
    SMTP_USER          (seu e-mail)
    SMTP_PASSWORD      (senha de app do Gmail)
    ALERT_FROM         (remetente exibido)
    ALERT_MANAGER_EMAIL (destinatário do resumo geral)

    # Mapeamento CS owner → e-mail (um por linha, formato: Nome=email@dominio.com)
    CS_EMAILS
"""

import os
import logging
import smtplib
import tempfile
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import date
from typing import Optional

import pandas as pd
import psycopg2
from dotenv import load_dotenv

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Paleta e estilos PDF ─────────────────────────────────────────────────────

C_ALTO     = colors.HexColor("#C0392B")
C_MEDIO    = colors.HexColor("#E67E22")
C_BAIXO    = colors.HexColor("#1E8449")
C_ACCENT   = colors.HexColor("#1A5276")
C_BG_HDR   = colors.HexColor("#F2F3F4")
C_BORDER   = colors.HexColor("#D5D8DC")
C_TEXT     = colors.HexColor("#1a1a1a")
C_DIM      = colors.HexColor("#7F8C8D")
C_ALTO_BG  = colors.HexColor("#FDEDEC")
C_MEDIO_BG = colors.HexColor("#FEF9E7")
C_BAIXO_BG = colors.HexColor("#EAFAF1")


def pdf_styles() -> dict:
    return {
        "title":        ParagraphStyle("title",        fontName="Helvetica-Bold", fontSize=18, textColor=C_ACCENT, spaceAfter=2),
        "sub":          ParagraphStyle("sub",           fontName="Helvetica",      fontSize=10, textColor=C_DIM,    spaceAfter=14),
        "h2":           ParagraphStyle("h2",            fontName="Helvetica-Bold", fontSize=12, textColor=C_ACCENT, spaceBefore=14, spaceAfter=6),
        "cell":         ParagraphStyle("cell",          fontName="Helvetica",      fontSize=8,  textColor=C_TEXT),
        "cell_bold":    ParagraphStyle("cell_bold",     fontName="Helvetica-Bold", fontSize=8,  textColor=C_TEXT),
        "cell_dim":     ParagraphStyle("cell_dim",      fontName="Helvetica",      fontSize=8,  textColor=C_DIM),
        "cell_alto":    ParagraphStyle("cell_alto",     fontName="Helvetica-Bold", fontSize=8,  textColor=C_ALTO),
        "cell_medio":   ParagraphStyle("cell_medio",    fontName="Helvetica-Bold", fontSize=8,  textColor=C_MEDIO),
        "cell_baixo":   ParagraphStyle("cell_baixo",    fontName="Helvetica-Bold", fontSize=8,  textColor=C_BAIXO),
        "action":       ParagraphStyle("action",        fontName="Helvetica",      fontSize=7,  textColor=C_DIM, leading=10),
        "footer":       ParagraphStyle("footer",        fontName="Helvetica",      fontSize=8,  textColor=C_DIM, alignment=1),
        "box_num_alto":  ParagraphStyle("box_num_alto",  fontName="Helvetica-Bold", fontSize=26, textColor=C_ALTO,  leading=30, spaceAfter=2),
        "box_num_medio": ParagraphStyle("box_num_medio", fontName="Helvetica-Bold", fontSize=26, textColor=C_MEDIO, leading=30, spaceAfter=2),
        "box_num_baixo": ParagraphStyle("box_num_baixo", fontName="Helvetica-Bold", fontSize=26, textColor=C_BAIXO, leading=30, spaceAfter=2),
        "box_lbl":      ParagraphStyle("box_lbl",       fontName="Helvetica",      fontSize=9,  textColor=C_DIM,  spaceAfter=3),
        "box_mrr":      ParagraphStyle("box_mrr",       fontName="Helvetica-Bold", fontSize=10, textColor=C_TEXT),
    }


def fmt_mrr(v) -> str:
    return f"R$ {int(v):,}".replace(",", ".")


def today_str() -> str:
    return date.today().strftime("%d/%m/%Y")


def suggest_actions(r: dict) -> str:
    a = []
    if r["sinal_engajamento"] >= 25: a.append("Agendar check-in de engajamento")
    if r["sinal_suporte"]     >= 15: a.append("Escalar tickets criticos")
    if r["has_overdue"]:             a.append("Contatar financeiro (overdue)")
    if r["contract_expiring_soon"]:  a.append("Iniciar renovacao contratual")
    if r["sinal_crm"]         >= 10: a.append("Pesquisa de satisfacao (NPS/Health)")
    return "\n".join(a) if a else "Monitorar"


def risk_style(level: str, s: dict):
    return {"Alto": s["cell_alto"], "Medio": s["cell_medio"], "Baixo": s["cell_baixo"]}[level]


def build_summary_boxes(rows: list, s: dict) -> Table:
    n_alto  = sum(1 for r in rows if r["risk_level"] == "Alto")
    n_medio = sum(1 for r in rows if r["risk_level"] == "Medio")
    n_baixo = sum(1 for r in rows if r["risk_level"] == "Baixo")
    mrr_alto  = sum(r["mrr"] for r in rows if r["risk_level"] == "Alto")
    mrr_medio = sum(r["mrr"] for r in rows if r["risk_level"] == "Medio")
    mrr_baixo = sum(r["mrr"] for r in rows if r["risk_level"] == "Baixo")

    def inner_box(n, label, mrr, num_style):
        t = Table([
            [Paragraph(str(n), num_style)],
            [Paragraph(label,  s["box_lbl"])],
            [Paragraph(fmt_mrr(mrr), s["box_mrr"])],
        ], colWidths=[52*mm])
        t.setStyle(TableStyle([
            ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ("TOPPADDING",    (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("LEFTPADDING",   (0,0), (-1,-1), 4),
            ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ]))
        return t

    outer = Table([[
        inner_box(n_alto,  "Risco Alto",  mrr_alto,  s["box_num_alto"]),
        inner_box(n_medio, "Risco Medio", mrr_medio, s["box_num_medio"]),
        inner_box(n_baixo, "Risco Baixo", mrr_baixo, s["box_num_baixo"]),
    ]], colWidths=[56*mm, 56*mm, 56*mm])

    outer.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,0), C_ALTO_BG),
        ("BACKGROUND", (1,0), (1,0), C_MEDIO_BG),
        ("BACKGROUND", (2,0), (2,0), C_BAIXO_BG),
        ("BOX",        (0,0), (0,0), 0.5, C_ALTO),
        ("BOX",        (1,0), (1,0), 0.5, C_MEDIO),
        ("BOX",        (2,0), (2,0), 0.5, C_BAIXO),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (-1,-1), 4),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
    ]))
    return outer


def build_data_table(rows: list, s: dict, include_owner: bool, include_actions: bool) -> Table:
    if include_actions:
        headers = ["#","Empresa","Plano","MRR","Score","Risco","Eng.","Sup.","Ctr.","CRM","Acoes Sugeridas"]
        col_w   = [8*mm,36*mm,18*mm,20*mm,12*mm,14*mm,9*mm,9*mm,9*mm,9*mm,44*mm]
    elif include_owner:
        headers = ["#","Empresa","CS Owner","Plano","MRR","Score","Risco","Eng.","Sup.","Ctr.","CRM"]
        col_w   = [8*mm,36*mm,26*mm,18*mm,20*mm,12*mm,14*mm,9*mm,9*mm,9*mm,9*mm]
    else:
        headers = ["#","Empresa","Plano","MRR","Score","Risco","Eng.","Sup.","Ctr.","CRM"]
        col_w   = [8*mm,42*mm,20*mm,22*mm,12*mm,14*mm,9*mm,9*mm,9*mm,9*mm]

    tbl_rows = [[Paragraph(f'<b>{h}</b>', s["cell_dim"]) for h in headers]]

    for r in rows:
        rs  = risk_style(r["risk_level"], s)
        row = [Paragraph(str(r["risk_rank"]), s["cell_dim"]),
               Paragraph(f'<b>{r["company_name"]}</b>', s["cell_bold"])]
        if include_owner:
            row.append(Paragraph(r["cs_owner"], s["cell_dim"]))
        row += [
            Paragraph(r["plan"], s["cell_dim"]),
            Paragraph(fmt_mrr(r["mrr"]), s["cell"]),
            Paragraph(f'<b>{r["churn_score"]}</b>', rs),
            Paragraph(r["risk_level"], rs),
            Paragraph(str(r["sinal_engajamento"]), s["cell"]),
            Paragraph(str(r["sinal_suporte"]),     s["cell"]),
            Paragraph(str(r["sinal_contrato"]),    s["cell"]),
            Paragraph(str(r["sinal_crm"]),         s["cell"]),
        ]
        if include_actions:
            row.append(Paragraph(suggest_actions(r).replace("\n", "<br/>"), s["action"]))
        tbl_rows.append(row)

    tbl  = Table(tbl_rows, colWidths=col_w, repeatRows=1)
    cmds = [
        ("BACKGROUND",     (0,0), (-1,0), C_BG_HDR),
        ("LINEBELOW",      (0,0), (-1,0), 0.8, C_ACCENT),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("LINEBELOW",      (0,1), (-1,-1), 0.3, C_BORDER),
        ("TOPPADDING",     (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
        ("LEFTPADDING",    (0,0), (-1,-1), 4),
        ("RIGHTPADDING",   (0,0), (-1,-1), 4),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ]
    for i, r in enumerate(rows, 1):
        if r["risk_level"] == "Alto":
            cmds.append(("BACKGROUND", (0,i), (-1,i), C_ALTO_BG))
        elif r["risk_level"] == "Medio":
            cmds.append(("BACKGROUND", (0,i), (-1,i), C_MEDIO_BG))
    tbl.setStyle(TableStyle(cmds))
    return tbl


def generate_pdf(rows: list, path: str, owner: Optional[str] = None) -> None:
    """
    Gera o PDF e salva em `path`.
    owner=None  → resumo geral (com coluna CS Owner)
    owner=<str> → carteira individual (com coluna de ações)
    """
    s   = pdf_styles()
    doc = SimpleDocTemplate(path, pagesize=A4,
        leftMargin=16*mm, rightMargin=16*mm,
        topMargin=16*mm, bottomMargin=16*mm)

    n_alto    = sum(1 for r in rows if r["risk_level"] == "Alto")
    n_medio   = sum(1 for r in rows if r["risk_level"] == "Medio")
    mrr_risco = sum(r["mrr"] for r in rows if r["risk_level"] in ("Alto", "Medio"))

    if owner:
        title_txt = f"Churn Alert — Carteira de {owner}"
        tbl_title = "Sua carteira com acoes sugeridas"
        tbl       = build_data_table(rows, s, include_owner=False, include_actions=True)
    else:
        title_txt = "Churn Alert — Resumo Geral"
        tbl_title = "Todos os clientes rankeados"
        tbl       = build_data_table(rows, s, include_owner=True, include_actions=False)

    story = [
        Paragraph(title_txt, s["title"]),
        Paragraph(
            f"{today_str()}  ·  {len(rows)} clientes  ·  "
            f"{n_alto} risco alto  ·  {n_medio} risco medio  ·  "
            f"MRR em risco: {fmt_mrr(mrr_risco)}",
            s["sub"]
        ),
        HRFlowable(width="100%", thickness=0.5, color=C_BORDER, spaceAfter=10),
        build_summary_boxes(rows, s),
        Spacer(1, 10),
        Paragraph(tbl_title, s["h2"]),
        tbl,
        Spacer(1, 16),
        HRFlowable(width="100%", thickness=0.3, color=C_BORDER, spaceBefore=4),
        Paragraph(
            f"Gerado automaticamente pelo pipeline de Churn Alert · {today_str()}",
            s["footer"]
        ),
    ]
    doc.build(story)


# ─── Helpers de conexão e dados ───────────────────────────────────────────────

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
    log.info(f"  {len(df)} clientes carregados")
    return df.to_dict(orient="records")


def parse_cs_emails() -> dict[str, str]:
    raw     = os.environ.get("CS_EMAILS", "")
    mapping = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if "=" in line:
            name, email = line.split("=", 1)
            mapping[name.strip()] = email.strip()
    return mapping


# ─── E-mail ───────────────────────────────────────────────────────────────────

def build_email_body(rows: list, owner: Optional[str] = None) -> str:
    """Corpo HTML simples do e-mail — o PDF é o conteúdo principal."""
    n_alto    = sum(1 for r in rows if r["risk_level"] == "Alto")
    n_medio   = sum(1 for r in rows if r["risk_level"] == "Medio")
    mrr_risco = sum(r["mrr"] for r in rows if r["risk_level"] in ("Alto","Medio"))

    greeting = f"Olá, {owner}!" if owner else "Olá, time de CS!"
    desc     = "Sua carteira está em anexo." if owner else "O resumo completo está em anexo."

    return f"""
    <html><body style="font-family:Arial,sans-serif;font-size:14px;color:#1a1a1a;">
      <h2 style="color:#1A5276;">🚨 Churn Alert — {today_str()}</h2>
      <p>{greeting} {desc}</p>
      <table style="border-collapse:collapse;margin:16px 0;">
        <tr>
          <td style="padding:10px 20px;background:#FDEDEC;border:1px solid #f5c6c6;border-radius:6px;text-align:center;">
            <div style="font-size:24px;font-weight:bold;color:#C0392B;">{n_alto}</div>
            <div style="font-size:11px;color:#888;">Risco Alto</div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:10px 20px;background:#FEF9E7;border:1px solid #f5dfa6;border-radius:6px;text-align:center;">
            <div style="font-size:24px;font-weight:bold;color:#E67E22;">{n_medio}</div>
            <div style="font-size:11px;color:#888;">Risco Médio</div>
          </td>
          <td style="width:12px;"></td>
          <td style="padding:10px 20px;background:#EAFAF1;border:1px solid #a9dfbf;border-radius:6px;text-align:center;">
            <div style="font-size:13px;font-weight:bold;color:#1E8449;">MRR em risco</div>
            <div style="font-size:12px;color:#555;">{fmt_mrr(mrr_risco)}</div>
          </td>
        </tr>
      </table>
      <p style="color:#888;font-size:12px;">
        Gerado automaticamente pelo pipeline de Churn Alert · {today_str()}
      </p>
    </body></html>
    """


def send_email(smtp: smtplib.SMTP, to: str, subject: str, html: str, pdf_path: str, pdf_name: str) -> None:
    msg             = MIMEMultipart("mixed")
    msg["Subject"]  = subject
    msg["From"]     = os.environ["ALERT_FROM"]
    msg["To"]       = to

    msg.attach(MIMEText(html, "html"))

    # Anexar PDF
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{pdf_name}"')
    msg.attach(part)

    smtp.sendmail(os.environ["ALERT_FROM"], to, msg.as_string())


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run() -> None:
    load_dotenv()

    log.info("=" * 55)
    log.info("  Iniciando pipeline de alertas de churn")
    log.info("=" * 55)

    data      = fetch_churn_score()
    cs_emails = parse_cs_emails()

    log.info(f"Conectando ao SMTP {os.environ['SMTP_HOST']}:{os.environ['SMTP_PORT']} ...")
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]))
    smtp.ehlo()
    smtp.starttls()
    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    log.info("  ✓ Conexão SMTP estabelecida\n")

    sent = errors = 0

    # 1. Resumo geral para o gestor
    manager_email = os.environ.get("ALERT_MANAGER_EMAIL")
    if manager_email:
        try:
            log.info(f"Gerando PDF de resumo geral ...")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
            generate_pdf(data, pdf_path, owner=None)

            pdf_name = f"churn_resumo_geral_{date.today().strftime('%Y%m%d')}.pdf"
            subject  = f"🚨 Churn Alert — Resumo Geral {today_str()}"
            html     = build_email_body(data)

            log.info(f"Enviando resumo geral para {manager_email} ...")
            send_email(smtp, manager_email, subject, html, pdf_path, pdf_name)
            log.info("  ✓ Resumo geral enviado\n")
            sent += 1
            os.unlink(pdf_path)
        except Exception as exc:
            log.error(f"  ✗ Erro ao enviar resumo geral: {exc}\n")
            errors += 1

    # 2. Carteira individual por CS owner
    owners = sorted(set(r["cs_owner"] for r in data if r["cs_owner"]))
    for owner in owners:
        email = cs_emails.get(owner)
        if not email:
            log.warning(f"  E-mail não configurado para '{owner}' — pulando")
            continue

        try:
            owner_rows = [r for r in data if r["cs_owner"] == owner]
            n_alto     = sum(1 for r in owner_rows if r["risk_level"] == "Alto")

            log.info(f"Gerando PDF para {owner} ({len(owner_rows)} clientes) ...")
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
            generate_pdf(owner_rows, pdf_path, owner=owner)

            owner_slug = owner.lower().replace(" ", "_")
            pdf_name   = f"churn_{owner_slug}_{date.today().strftime('%Y%m%d')}.pdf"
            subject    = (
                f"🚨 Churn Alert — Sua Carteira {today_str()} "
                f"({n_alto} em risco alto)"
            )
            html = build_email_body(owner_rows, owner=owner)

            log.info(f"Enviando para {owner} ({email}) ...")
            send_email(smtp, email, subject, html, pdf_path, pdf_name)
            log.info(f"  ✓ Enviado para {owner}\n")
            sent += 1
            os.unlink(pdf_path)
        except Exception as exc:
            log.error(f"  ✗ Erro ao enviar para {owner}: {exc}\n")
            errors += 1

    smtp.quit()

    log.info("=" * 55)
    log.info(f"  ✓ {sent} e-mails enviados  ·  ✗ {errors} erros")
    log.info("=" * 55)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()
