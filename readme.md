# FinSpark — AI Integration Orchestration Engine

> **Theme:** Configure Enterprise Integrations from Intent, Not Code

Transform requirement documents (BRDs, SOWs) into production-ready integration configurations using AI — eliminating weeks of manual configuration work.

---

## The Problem

Enterprise lending platforms integrate with bureaus, KYC providers, GST services, fraud engines, and payment gateways. Today this process is:

- Manual BRD analysis by implementation teams
- Repetitive schema mapping across every client
- Error-prone API version selection
- Weeks of sandbox testing cycles

**FinSpark reduces this from 6 weeks to under 60 seconds.**

---

## What It Does

```
Paste BRD text
      ↓
AI extracts services + mandatory flags
      ↓
Semantic field mapping with confidence scores
      ↓
Auto-generated per-tenant YAML config
      ↓
Sandbox simulation with fallback validation
      ↓
Production-ready integration config
```

---

## Architecture

```
finspark-engine/
│
├── brd_parser.py        # Stage 1 — NLP parsing with Groq Llama 3.3
├── mapper.py            # Stage 2 — Semantic field mapping (embeddings)
├── config_gen.py        # Stage 3 — YAML config generation (Jinja2)
├── simulator.py         # Stage 4 — Sandbox simulation + fallback
├── healer.py            # Stage 5 — Self-healing loop (AI auto-fix)
├── audit.py             # Audit trail — append-only run logs
├── registry.py          # Dynamic adapter registry (SQLite)
├── diff.py              # Version diff engine
├── tenants.py           # Multi-tenant isolation
├── app.py               # Streamlit UI
│
├── templates/
│   └── adapter_config.yaml.j2   # Jinja2 config template
│
├── configs/             # Generated per-tenant YAML configs
├── tenants/             # Per-tenant isolated data
├── audit/               # Audit logs
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| LLM | Groq Llama 3.3 70B | BRD parsing, self-healing |
| Embeddings | sentence-transformers | Semantic field mapping |
| Similarity | scikit-learn cosine similarity | Confidence scoring |
| Templating | Jinja2 | Config generation |
| Config format | YAML + PyYAML | Integration configs |
| Validation | Pydantic | Schema enforcement |
| Database | SQLite | Adapter registry |
| UI | Streamlit | Browser interface |
| Deployment | Docker + docker-compose | One-command setup |

---

## Quick Start

### Option 1 — Run with Docker (recommended)

```bash
git clone https://github.com/your-team/finspark-engine
cd finspark-engine
cp .env.example .env
# Add your GROQ_API_KEY to .env
docker-compose up
```

Open [http://localhost:8501](http://localhost:8501)

### Option 2 — Run locally

**Prerequisites:**
- Python 3.10+
- A free Groq API key from [console.groq.com](https://console.groq.com)

```bash
git clone https://github.com/your-team/finspark-engine
cd finspark-engine

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# Run the app
streamlit run app.py
```

---

## Environment Variables

Create a `.env` file based on `.env.example`:

```env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
```

Get your free Groq API key at [console.groq.com](https://console.groq.com) — no credit card required.

---

## How to Use

### Step 1 — Paste your BRD

Paste any requirement document into the text area. Example:

```
Acme Lending requires CIBIL for credit bureau checks (mandatory).
UIDAI Aadhaar eKYC is mandatory for all borrowers.
GST verification via NIC is optional for MSME loans.
Razorpay penny drop is mandatory for bank account validation.
```

### Step 2 — Run the pipeline

Click **Run pipeline**. The engine will:

1. Extract all integration services using AI
2. Map your schema fields to each provider's API fields
3. Generate a production-ready YAML config
4. Simulate each integration in sandbox
5. Auto-fix any failures (self-healing)
6. Log the run to the audit trail

### Step 3 — Download config

Download the generated YAML config file directly from the UI.

### Step 4 — Test failure scenarios

Use the sidebar to force specific adapters to fail — demonstrates the self-healing loop and fallback behavior live.

---

## Supported Providers

| Provider | Type | Adapter |
|----------|------|---------|
| CIBIL | Credit Bureau | cibil-bureau-adapter@v3.1 |
| Experian | Credit Bureau | experian-bureau-adapter@v2.9 |
| UIDAI | eKYC | uidai-ekyc-adapter@v2.4 |
| NIC | GST Verification | nic-gst-adapter@v1.8 |
| GSTN | GST Verification | gstn-verification-adapter@v1.2 |
| Razorpay | Bank Verification | razorpay-penny-drop-adapter@v4.0 |
| PayU | Payment Gateway | payu-payment-gateway-adapter@v5.3 |

New providers can be added through the admin panel — no code changes required.

---

## Sample Output

### Parsed requirements
```json
{
  "tenant_id": "acme_lending",
  "services": [
    { "id": "cibil", "type": "credit_bureau", "provider": "CIBIL", "mandatory": true },
    { "id": "uidai_ekyc", "type": "kyc", "provider": "UIDAI", "mandatory": true },
    { "id": "gst_nic", "type": "gst", "provider": "NIC", "mandatory": false }
  ]
}
```

### Generated config
```yaml
tenant_id: acme_lending
version: "1.0.0"
environment: sandbox

integrations:
  cibil:
    adapter: cibil-bureau-adapter@v3.1
    mandatory: true
    auth: vault://acme_lending/cibil/api_key
    timeout_ms: 3000
    fallback: fail_closed

  gst_nic:
    adapter: nic-gst-adapter@v1.8
    mandatory: false
    auth: vault://acme_lending/gst_nic/api_key
    timeout_ms: 2500
    fallback: skip
```

### Simulation results
```
✅ cibil-bureau-adapter       — 1200ms — pass
✅ uidai-ekyc-adapter         — 890ms  — pass
✅ nic-gst-adapter            — 654ms  — pass
✅ razorpay-penny-drop-adapter — 445ms  — pass

All mandatory integrations passed. Config is ready for deployment.
```

---

## Security Design

| Concern | Implementation |
|---------|---------------|
| Credentials | Never stored in config — vault:// references only |
| Tenant isolation | Per-tenant folders, scoped configs and audit logs |
| Audit trail | Append-only JSON log of every pipeline run |
| Fallback | Mandatory services fail_closed, optional services skip |
| Secrets | Loaded from .env, never hardcoded |

---

## Business Impact

| Metric | Before | After |
|--------|--------|-------|
| Implementation cycle | 4-6 weeks | Under 60 seconds |
| Config defect rate | High (manual) | Near zero (validated) |
| Client onboarding | Weeks | Hours |
| Audit readiness | Manual effort | Automatic |

---

## Scoring Criteria Coverage

| Criteria | Weight | How we address it |
|----------|--------|------------------|
| Enterprise Realism | 20% | Real fintech providers, vault references, fallback rules, per-tenant isolation |
| AI Practicality | 15% | Groq LLM for parsing, embeddings for mapping, confidence scoring |
| Backward Compatibility | 15% | Version pinning, diff engine, migration warnings |
| Multi-Tenant Scalability | 15% | Per-tenant folders, scoped configs, SQLite registry |
| Security & Compliance | 15% | Vault references, audit trail, no plaintext secrets |
| Business Impact | 10% | 6 weeks → 60 seconds, validated configs, faster onboarding |
| Ease of Deployability | 10% | Docker one-command setup, clear README, .env.example |

---

## Team

Built at FinSpark Hackathon 2026

---

## License

MIT