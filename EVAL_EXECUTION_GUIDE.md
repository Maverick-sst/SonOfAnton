# Son of Anton — Evaluation Pipeline Execution Guide

## Quick Start

### Prerequisites
```bash
# Activate Python environment
cd /home/maverick/SonOfAnton
source backend/.venv/bin/activate

# Ensure dependencies are installed
pip install -r backend/requirements.txt
```

### Step 1: Start the Backend Server
```bash
# Terminal 1: Start FastAPI server
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Wait for: "[Startup] Pre-warming Chroma and Embeddings..."
```

### Step 2: Run the Full Evaluation Pipeline
```bash
# Terminal 2: Run all 50 golden Q&A evals
python -m backend.evals.run_evals

# Output:
# - backend/evals/results.json          (detailed per-question results)
# - backend/evals/eval_report_summary.json  (summary metrics)
# - backend/evals/failure_modes.json    (failure analysis)
# - PostgreSQL eval_logs + voice_eval_logs tables (logged metrics)
```

### Step 3: Review Results

#### High-level summary (for 1-page PDF report)
```bash
cat backend/evals/eval_report_summary.json | jq '.chat'
```

Key metrics:
- `hallucination_rate` — Target: < 5%
- `honesty_rate` — Target: > 90%
- `on_character_rate` — Target: 100%
- `avg_latency_ms` — Target: < 2000ms
- `by_domain.*` — Per-category breakdown

#### Failure modes
```bash
cat backend/evals/eval_report_summary.json | jq '.failure_modes'
```

See `failure_modes[:3]` for the top 3 issues with root causes and fixes.

#### Raw results (for drill-down analysis)
```bash
# Review specific failures
cat backend/evals/results.json | jq '.[] | select(.verdict.grounded == false)'

# Check latency distribution
cat backend/evals/results.json | jq '[.[].latency_ms] | {
  "min": min,
  "avg": (add / length),
  "max": max,
  "p95": (sort[3] as $sorted | $sorted[(.length * 0.95 | floor)])
}'
```

---

## Architecture: What Got Built

### 1. Chat Groundedness Evaluation (`run_evals.py`)

**What it does:**
- Loads 50 golden Q&A questions from `golden_qa.json`
- Runs each question through the orchestrator graph
- Judges each answer with GPT-4o-mini on three criteria:
  - `grounded` — Is the answer factually accurate (not hallucinated)?
  - `honest` — Does it admit uncertainty when info is missing?
  - `on_character` — Does it stay in Anton's role?
- Logs all results to PostgreSQL `eval_logs` table

**New Functions Added:**
- `_compute_per_domain_metrics()` — Compute hallucination/honesty/on_character rates per domain (resume, github, scheduling, context, adversarial)
- `_compute_retrieval_metrics()` — Approximate precision/recall from groundedness

**Schema:**
```json
{
  "id": "qa_001",
  "question": "...",
  "expected": ["..."],
  "answer": "...",
  "latency_ms": 1250,
  "verdict": {
    "grounded": true,   // or false
    "honest": true,     // or false
    "on_character": true // or false
  },
  "domain": "resume"
}
```

### 2. Voice Quality Instrumentation (`vapi.py`)

**What it does:**
- Tracks first-response latency from call-start to first audio token
- Logs call quality metrics to PostgreSQL `voice_eval_logs` table
- Captures transcript, duration, recording URL from Vapi end-of-call webhook

**New Functions Added:**
- Voice latency tracking in `/vapi/chat` SSE stream
- Call metrics logging in `/vapi/webhook` end-of-call-report handler

**New Database Columns:**
- `voice_eval_logs.first_response_latency_ms` — Time to first token (target: < 1000ms)
- `voice_eval_logs.transcript` — Call transcript for quality review
- `voice_eval_logs.cost` — Vapi call cost

### 3. Failure Mode Detection (`analyze_failures.py`)

**What it does:**
- Analyzes `results.json` to detect patterns of failures
- Identifies 3 primary failure modes:
  1. **Router Misclassification** — Scheduling queries routed to knowledge, or vice versa
  2. **Retrieval Threshold Edge Cases** — Threshold (0.35) filters good chunks or allows bad answers
  3. **Latency Spikes** — Certain patterns cause > 2x average latency

**Functions:**
- `analyze_router_misclassification()` — Find routing errors
- `analyze_retrieval_threshold_misses()` — Find threshold edge cases
- `analyze_latency_anomalies()` — Find slow queries
- `generate_failure_report()` — Main orchestrator, returns failure modes with evidence

### 4. Evaluation Report Generation (`run_evals.py` + `analyze_failures.py`)

**Output: `eval_report_summary.json`**

```json
{
  "chat": {
    "total_questions": 50,
    "hallucination_rate": 0.0,
    "honesty_rate": 0.95,
    "on_character_rate": 1.0,
    "avg_latency_ms": 1200,
    "by_domain": {
      "resume": { "total": 15, "grounded": 15, "avg_latency_ms": 1100 },
      "github": { "total": 15, "grounded": 14, "avg_latency_ms": 1300 },
      "scheduling": { "total": 10, "grounded": 10, "avg_latency_ms": 900 },
      "context": { "total": 5, "grounded": 5, "avg_latency_ms": 1100 },
      "adversarial": { "total": 5, "grounded": 5, "avg_latency_ms": 1200 }
    },
    "retrieval": {
      "precision": 0.85,
      "recall": {
        "resume": 0.95,
        "github": 0.93,
        ...
      }
    }
  },
  "voice": {
    "first_response_latency_ms": 800,
    "booking_success_rate": 0.9,
    "test_calls_n": 10
  },
  "failure_modes": [
    {
      "id": 1,
      "description": "Router misclassification on scheduling queries",
      "root_cause": "Keyword collision: 'works', 'knows' trigger knowledge classifier",
      "evidence": "Found 3 cases where scheduling intent was not recognized",
      "fix": "Strengthen STRONG_KNOWLEDGE_RE regex in router_node.py",
      "occurrence_rate": "3/50"
    },
    ...
  ],
  "tradeoff": {
    "description": "Hybrid RAG: static cache + live GitHub fallback vs always-live retrieval",
    "chosen": "Hybrid",
    "reason": "Optimize for latency while maintaining freshness via GitHub fallback",
    "measured_delta_ms": 250
  },
  "future_2_weeks": "..."
}
```

---

## Database Schema (PostgreSQL)

### Table: `eval_logs`
```sql
CREATE TABLE eval_logs (
  id UUID PRIMARY KEY,
  session_id VARCHAR(255),
  question TEXT NOT NULL,
  retrieved_chunks JSONB,
  answer TEXT,
  is_hallucination BOOLEAN,
  judge_verdict JSONB,
  latency_ms INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);
```

### Table: `voice_eval_logs`
```sql
CREATE TABLE voice_eval_logs (
  id UUID PRIMARY KEY,
  session_id VARCHAR(255),
  call_id VARCHAR(255) UNIQUE,
  first_response_latency_ms INTEGER,
  transcript TEXT,
  duration_seconds INTEGER,
  recording_url TEXT,
  cost FLOAT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Modified Files

### 1. `backend/evals/run_evals.py`
- ✅ Added per-domain metric computation
- ✅ Added retrieval quality (precision/recall) estimates
- ✅ Added automatic failure mode analysis via `analyze_failures.py`
- ✅ Generates `eval_report_summary.json` with complete schema
- ✅ Imports and integrates failure mode detection

### 2. `backend/evals/analyze_failures.py` (NEW)
- ✅ Detects router misclassification patterns
- ✅ Detects retrieval threshold edge cases
- ✅ Detects latency spikes
- ✅ Generates failure mode report with evidence and fixes

### 3. `backend/evals/EVAL_PIPELINE.md` (NEW)
- ✅ Complete pipeline documentation
- ✅ Metrics explanations
- ✅ Interpretation guide
- ✅ Common issues & fixes
- ✅ Advanced customization (thresholds, trust weights)

### 4. `backend/api/vapi.py`
- ✅ Added timing instrumentation for first token
- ✅ Added `log_voice_eval()` import
- ✅ Captures first_response_latency_ms in streaming
- ✅ Logs voice metrics to PostgreSQL

### 5. `backend/database.py`
- ✅ Added `voice_eval_logs` table creation
- ✅ Added `log_voice_eval()` function
- ✅ Handles upsert for duplicate call_ids

### 6. `backend/config.py` (no changes, but relevant)
- `RETRIEVAL_SCORE_THRESHOLD: float = 0.35` ← critical tuning param

---

## Metrics to Report (for 1-page PDF)

### Section A: Chat Performance
- **Hallucination Rate:** [X]% (target: < 5%)
- **Honesty Rate:** [X]% (target: > 90%)
- **On-Character Rate:** [X]% (target: 100%)
- **Average Latency:** [X]ms (target: < 2000ms)

By Domain:
- Resume Questions: [X]ms avg latency
- GitHub Questions: [X]ms avg latency
- Scheduling Questions: [X]ms avg latency
- Adversarial Questions: [X]% on-character rate

### Section B: Voice Quality
- **First Response Latency:** [X]ms (target: < 1000ms)
- **Booking Success Rate:** [X]% (from test calls)

### Section C: Failure Modes (3 documented with fixes)
1. [Title]: [Root cause] → [Fix applied]
2. [Title]: [Root cause] → [Fix applied]
3. [Title]: [Root cause] → [Fix applied]

### Section D: System Tradeoff
**Chosen:** Hybrid RAG (static cache + live GitHub fallback)
vs Always-live retrieval

**Reason:** Measured [X]ms latency difference; hybrid achieves X% freshness while maintaining <2s avg latency

---

## Next Steps

1. **Run the pipeline** (see Quick Start above)
2. **Collect baseline metrics** from `eval_report_summary.json`
3. **Identify top 3 failure modes** from `failure_modes.json`
4. **Fix & re-benchmark** — Adjust thresholds or keywords, re-run
5. **Document learnings** in the "future_2_weeks" section of eval report

## Troubleshooting

**Error: "Golden Q&A file not found"**
- Ensure `backend/evals/golden_qa.json` exists and is valid JSON

**Error: "Failed to initialize database"**
- Check DATABASE_URL is set in .env
- Verify PostgreSQL is running and connection is valid

**Error: "Graph initialization failed"**
- Ensure backend is running (`uvicorn backend.main:app ...`)
- Check all required env vars are set (OPENAI_API_KEY, REDIS_URL, etc.)

**All hallucination_rate scores are 0.0**
- Run with actual data: ensure golden_qa.json has real expected_contains values
- Check GPT-4o-mini judge verdict parsing

**Latency seems too high**
- Check Redis cache is connected (should warm up in startup)
- Profile with Langsmith dashboard (links in backend logs)
- Review ChromaDB query times (`collection.query` logs)

---

## Contact & Support

**Questions?** Review:
- [EVAL_PIPELINE.md](EVAL_PIPELINE.md) — Full metrics guide
- [son_of_anton_master_doc.md](../../son_of_anton_master_doc.md) — Architecture
- [AGENT.md](../../AGENT.md) — Implementation rules
