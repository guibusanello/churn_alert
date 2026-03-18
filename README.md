# Churn Alert

Pipeline de dados end-to-end que monitora risco de churn de clientes B2B e envia alertas automáticos por e-mail para o time de Customer Success.

---

## Visão Geral

Empresas SaaS perdem receita quando clientes cancelam sem aviso. Esse projeto simula um pipeline real de engenharia de dados que cruza dados de três fontes distintas, calcula um score de risco por cliente e dispara alertas automáticos com PDFs personalizados para cada CS owner.

**Fontes de dados simuladas:**
- **CRM** (Salesforce) — dados de contas, contratos, health score e NPS
- **User Activity** (Amplitude) — eventos de uso do produto por sessão
- **Support Tickets** (Zendesk/Intercom) — tickets abertos, prioridade e CSAT

**Produto final:** e-mails automáticos com PDF anexado contendo o ranking de clientes por risco de churn, enviados individualmente para cada CS owner e em resumo geral para o gestor.

---

## Arquitetura Medalhão

O pipeline segue a arquitetura medalhão com três camadas no Supabase (PostgreSQL):

```
┌─────────────────────────────────────────────────────────────┐
│  BRONZE — schema bronze                                     │
│  Dados brutos ingeridos via load_csv.py, sem transformação  │
│                                                             │
│  bronze.crm_accounts        bronze.crm_contracts            │
│  bronze.user_activity_events  bronze.support_tickets        │
└────────────────────┬────────────────────────────────────────┘
                     │ REFRESH
┌────────────────────▼────────────────────────────────────────┐
│  SILVER — schema silver (Materialized Views)                │
│  Limpeza, padronização e identity resolution                │
│                                                             │
│  • TRIM, INITCAP, LOWER em campos de texto                  │
│  • Valores lixo (n/a, null, -, etc.) convertidos em NULL    │
│  • Deduplicação de eventos e tickets                        │
│  • Identity resolution via domínio de e-mail:               │
│    billing@company.com = admin@company.com = joao@company.com│
│    → todos resolvidos para o mesmo account_id do CRM        │
│                                                             │
│  silver.crm_accounts        silver.crm_contracts            │
│  silver.user_activity_events  silver.support_tickets        │
└────────────────────┬────────────────────────────────────────┘
                     │ REFRESH
┌────────────────────▼────────────────────────────────────────┐
│  GOLD — schema gold (Materialized View)                     │
│  Lógica de negócio pura — churn score por cliente           │
│                                                             │
│  Sinais utilizados:                                         │
│  • Queda de engajamento 30d vs 30d anterior  (0–30 pts)     │
│  • Tickets críticos abertos                  (0–25 pts)     │
│  • Pagamento overdue / contrato vencendo     (0–25 pts)     │
│  • Health score e NPS baixos                 (0–20 pts)     │
│                                                             │
│  gold.churn_score                                           │
└─────────────────────────────────────────────────────────────┘
```
---

## Setup e Execução

### Pré-requisitos

- Python 3.11+
- Conta no [Supabase](https://supabase.com) com projeto criado
- Conta Gmail com [senha de app](https://myaccount.google.com/apppasswords) habilitada

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/churn-alert.git
cd churn-alert
```

### 2. Criar ambiente virtual e instalar dependências

```bash
python -m venv .venv
source .venv/bin/activate       # Mac/Linux
.venv\Scripts\activate          # Windows

pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencha o `.env` com suas credenciais:

```bash
# Supabase — Project Settings → Database → Connection parameters
SUPABASE_HOST=db.<sua-referencia>.supabase.co
SUPABASE_PORT=5432
SUPABASE_DB=postgres
SUPABASE_USER=postgres
SUPABASE_PASSWORD=<sua-senha>

# SMTP — use senha de app do Gmail, não a senha normal
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu@gmail.com
SMTP_PASSWORD=<senha-de-app>
ALERT_FROM=Churn Alert <seu@gmail.com>
ALERT_MANAGER_EMAIL=gestor@empresa.com

# Mapeamento CS owner → e-mail (um por linha)
CS_EMAILS=Ana Lima=ana@empresa.com
    Carlos Souza=carlos@empresa.com
    Fernanda Rocha=fernanda@empresa.com
    Bruno Alves=bruno@empresa.com
    Juliana Matos=juliana@empresa.com
```

### 4. Criar as tabelas no Supabase

No **SQL Editor** do Supabase, execute as queries na seguinte ordem:

**Etapa 1** — Criar os schemas:
```sql
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
```

**Etapa 2** — Criar as tabelas bronze no schema `public` e movê-las:
```sql
-- Após criar as tabelas crm_accounts, crm_contracts,
-- user_activity_events e support_tickets no schema public:
ALTER TABLE public.crm_accounts         SET SCHEMA bronze;
ALTER TABLE public.crm_contracts        SET SCHEMA bronze;
ALTER TABLE public.user_activity_events SET SCHEMA bronze;
ALTER TABLE public.support_tickets      SET SCHEMA bronze;
```

**Etapa 3** — Criar as Materialized Views silver (uma por tabela) com limpeza e identity resolution.

**Etapa 4** — Criar a Materialized View `gold.churn_score`.

### 5. Ingerir os dados

```bash
python ingestion/load_csv.py --data-dir data
```

O script valida os dados, faz upsert idempotente no bronze e executa o `REFRESH` de todas as Materialized Views silver e gold automaticamente ao final.

### 6. Enviar os alertas

```bash
python alerts/send_alerts.py
```

O script lê o `gold.churn_score`, gera um PDF por destinatário e envia os e-mails com o PDF anexado. Cada CS owner recebe apenas sua carteira; o gestor recebe o resumo completo de todos os clientes.

---

## Tecnologias Utilizadas

| Camada | Tecnologia |
|---|---|
| Banco de dados | Supabase (PostgreSQL) |
| Transformação | SQL — Materialized Views |
| Ingestão | Python, psycopg2, pandas |
| Geração de PDF | ReportLab |
| Envio de e-mail | Python smtplib, SMTP Gmail |

---
