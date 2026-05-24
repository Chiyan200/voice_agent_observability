# Voice Agent Observability — REST + WebSocket API

Full-stack FastAPI service that sits on top of the existing MongoDB collections
(`call_histories` and `post_call_analyses`) and exposes:

- **REST API** for call replay, failure detection, and drift analytics  
- **WebSocket** live monitoring feed with real-time anomaly surfacing

---

## Project Structure (MVC Pattern)

```
voice_obs_api/
├── main.py                          ← FastAPI app, lifespan, CORS
├── requirements.txt
├── .env                             ← (create from .env.example)
│
├── core/
│   ├── config.py                    ← Pydantic settings (env vars)
│   └── database.py                  ← Motor singleton
│
├── models/
│   └── response_models.py           ← All Pydantic request/response models
│
├── services/                        ← Business logic (Model layer)
│   ├── calls_service.py             ← Call queries, latency enrichment, failure taxonomy
│   ├── analysis_service.py          ← Post-call analysis queries, failure reports
│   └── monitor_service.py           ← Anomaly detection, live stream simulation
│
├── api/
│   ├── controllers/                 ← Translate service data ↔ Pydantic models
│   │   ├── calls_controller.py
│   │   └── analysis_controller.py
│   └── routers/                     ← HTTP route definitions (thin, no logic)
│       ├── calls.py
│       ├── analysis.py
│       └── monitor.py
│
└── websocket/
    └── connection_manager.py        ← WS pool: per-call + global subscribers
```

---

## Setup

### 1. Install dependencies

```bash
cd voice_obs_api
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file (or set environment variables):

```env
MONGO_URI=mongodb://localhost:27017/
MONGO_DB=voice_agent_obs
```

### 3. Run the server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive docs: http://localhost:8000/docs

---

## REST API Reference

### Calls

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/calls` | List all calls (paginated). Query params: `page`, `page_size`, `user_id`, `call_type` |
| `GET` | `/calls/failures` | **Task 1** — failure detection summary with counts and sample call_ids per category |
| `GET` | `/calls/{call_id}` | Full call document with all observations |
| `GET` | `/calls/{call_id}/replay` | All turns enriched with agent response latency |
| `POST` | `/calls/{call_id}/seek?turn=N` | Jump to a specific turn index |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/analysis/dashboard` | **Task 4** — latency stats, tool success rates, sentiment trends, outliers |
| `GET` | `/analysis/{call_id}` | Full post-call analysis document |
| `GET` | `/analysis/{call_id}/report` | **Task 2** — structured failure attribution report per call |

### Live Monitor

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/monitor/anomalies` | One-shot anomaly scan across all stored calls |
| `POST` | `/monitor/simulate/{call_id}` | **Task 5** — trigger live replay simulation |
| `WS` | `/monitor/ws` | Global live feed (all calls) |
| `WS` | `/monitor/ws/{call_id}` | Per-call live feed |

---

## WebSocket Live Monitor Usage

### 1. Connect first, then simulate

```javascript
// Step 1: open WS connection
const ws = new WebSocket("ws://localhost:8000/monitor/ws/call_35b3ee8c-...");
ws.onmessage = (e) => console.log(JSON.parse(e.data));

// Step 2: trigger simulation
fetch("http://localhost:8000/monitor/simulate/call_35b3ee8c-...", { method: "POST" });
```

### Event schema

```json
{
  "event_type": "observation | anomaly | call_start | call_end | error",
  "call_id":    "call_35b3ee8c-...",
  "severity":   "info | warning | critical",
  "message":    "Tool failure: check_account_balance → Invalid account ID: 99999",
  "payload":    { "tool_name": "check_account_balance", "turn_index": 4 },
  "timestamp_ms": 1779560034429
}
```

### Global dashboard feed

```javascript
const ws = new WebSocket("ws://localhost:8000/monitor/ws");
// Receives anomalies and lifecycle events from ALL active simulations
```

---

## Failure Taxonomy (Task 1)

| Category | Detection Rule |
|----------|---------------|
| `tool_failure` | ≥ 2 `tool_status == "failure"` observations in a call |
| `latency_spike` | Any agent response latency > 3 000 ms |
| `sentiment_crash` | `detected_emotion == "frustrated"` or ≥ 3 "excited" turns |
| `hallucination` | Duplicate LLM response content across turns |
| `topic_drift` | User repeated same utterance ≥ 2 times |
| `incomplete_resolution` | Tool failures present with no subsequent successful tool call |

---

## Failure Attribution Report (Task 2)

`GET /analysis/{call_id}/report` returns:

```json
{
  "call_id": "call_35b3ee8c-...",
  "call_duration_sec": 59,
  "total_turns": 13,
  "hallucination_detected": true,
  "unresolved_queries": ["Check balance for account 99,999"],
  "failure_turns": [
    {
      "turn_index": 4,
      "turn_id": "turn_5bce6ce7-...",
      "type": "tool_call",
      "content": "",
      "root_causes": [
        {
          "category": "tool_failure",
          "what_happened": "Tool 'check_account_balance' called with input {\"account_id\": \"99999\"} returned: Invalid account ID: 99999",
          "what_should_happen": "Agent should validate the account ID format before calling the tool, or surface the exact API error to the user."
        }
      ]
    }
  ],
  "overall_failure_categories": ["tool_failure", "hallucination"],
  "qa_summary": "The user requested a balance check..."
}
```
