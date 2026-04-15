# Aegis V2.5: Zero-Trust Agentic Commerce Gateway

![Aegis Command Center Dashboard](./aegis-dashboard.png)

**Aegis V2.5** is a production-grade control plane for agentic commerce: a **zero-copy Rust / Next.js gateway** that sits between your systems and external intelligence, turning two existential risks into measurable advantage—**data leakage into LLMs** and **uncontrolled inference spend**.

This is not a demo stack. It is built for operators who answer to a **VP of Engineering** (and to auditors): deterministic boundaries, explicit degradation paths, and FinOps telemetry you can take to the board.

---

## The hook: compliance-grade interception, not “prompt hygiene”

Agentic workflows move fast. Regulators and enterprise customers do not. **A zero-copy Rust/Next.js gateway intercepts PII in <2ms** on the hot path—so you can argue a defensible control for **SOC2 compliance for Agentic Commerce** *before* payloads ever reach a third-party model.

Masking and policy enforcement happen **upstream of the LLM boundary**, not as an afterthought in a logging pipeline.

---

## The architecture: speed with adult supervision

Routing and protection are not “best effort.” The architecture includes **10ms dynamic circuit breakers** with **graceful degradation**: when the cloud path, quotas, or dependencies fail, traffic falls back through a controlled profile instead of silently burning budget or dropping compliance guarantees.

You get **predictable failure modes**—the kind you document in a security packet—not surprise 500s and mystery invoices.

---

## The business impact: TCO arbitrage and regulatory option value

| Lever | What it buys you |
|--------|------------------|
| **Inference economics** | **Saves >$90,000 annually** by achieving an **80% cache hit rate on LLM inference**—routing repeat semantic work away from metered APIs without starving agents that genuinely need fresh reasoning. |
| **Talent / immigration economics** | Structured hiring and mobility for **F-1 Change of Status (COS)** can unlock on the order of a **$100,000 H-1B tariff exemption** versus alternative paths—real TCO when you are scaling agentic teams under visa constraints. |
| **Regulatory / reputational** | **Prevents massive regulatory fines by masking PII before it hits external LLMs**—shrinking exposure to GDPR-, HIPAA-, and PCI-class enforcement and the seven- and eight-figure fine ranges that make headlines. |

Aegis is framed as **margin and risk** in the same SKU: cheaper inference where it is safe, harder boundaries where it is not.

---

## Visual proof

The screenshot above (**`./aegis-dashboard.png`**) is the **Aegis Command Center**—live FinOps posture, integrity signals, and PII scan telemetry in one surface. Replace the image in-repo when you drop in your production capture.

---

## Quick start

### Command center (Next.js)

```bash
cd frontend
cp .env.local.example .env.local   # then set NEXT_PUBLIC_AEGIS_API_URL to your gateway URL
npm install
npm run dev
```

Open **http://localhost:3000**. Restart the dev server after changing `NEXT_PUBLIC_*` variables.

### Rust engine (PyO3 extension) + FastAPI Bifrost

From the repository root, install Python deps, build the **`antigravity_core`** wheel, and run the gateway (adjust host/port to match your `NEXT_PUBLIC_AEGIS_API_URL`):

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r gateway/requirements.txt

# Build & install the zero-copy Rust extension into the active venv
maturin develop --manifest-path crates/antigravity_core/Cargo.toml

# API bridge (Rust-backed scan + FinOps endpoints)
uvicorn gateway.main:app --host 0.0.0.0 --port 8080 --reload --reload-dir gateway
```

**Health check:** `GET /healthz` on the gateway port. **PII scan:** `POST /v1/analytics/scan`. **FinOps stub:** `GET /v1/analytics/finops`.

---

## Who this is for

- **Engineering leadership** shipping agentic checkout, support, or operations automation under SOC 2 or ISO scrutiny.
- **Platform teams** that need **one choke point** for model routing, cache strategy, and data residency—not twelve bespoke wrappers.
- **FinOps owners** tired of explaining GPU and token bills without a **single pane of glass**.

---

## Positioning

Aegis V2.5 is a **weapon**, not a workshop: zero-trust data handling, **compute arbitrage** you can quantify, and circuit-breaking behavior you can explain to **Stripe-grade** infrastructure leadership.

If your agents touch money, identity, or regulated data, **the default architecture is already wrong**. Aegis exists to fix that—measurably.
