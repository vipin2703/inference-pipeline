# Local RAG System — vLLM Backend + Observability

A local, Docker-based LLM serving stack built around vLLM, with a FastAPI backend proxy and Langfuse observability. This README documents the architecture and design decisions made so far.

---

## 1. Project Structure

```
rag/
├── config/
│   ├── .env                    # vLLM server config (model path, GPU settings, etc.)
│   └── docker-compose.yml      # Orchestrates vllm-server, backend, and Langfuse stack
│
├── backend/
│   ├── Dockerfile
│   ├── main.py                 # FastAPI app init + router registration only
│   ├── vllm/
│   │   └── .env                 # BASE_URL, MODEL_NAME, Langfuse keys (container-scoped)
│   └── vllm_service/
│       ├── __init__.py
│       ├── client.py            # LLM call logic (business logic layer)
│       ├── routes.py            # HTTP endpoints (/health, /chat, /chat/stream)
│       └── schemas.py           # Pydantic request/response models
│
├── chat_client.py               # Standalone terminal client for testing the backend
└── client_/                     # Separate standalone script (direct vLLM/Azure client)
    ├── client.py
    ├── Dockerfile
    └── requirements.txt
```

### Design principle: feature-based (vertical slice) architecture

Instead of grouping files by technical layer (all routes together, all schemas together), each service owns a self-contained folder with its own `client.py`, `routes.py`, and `schemas.py`. This was a deliberate choice for a project that will eventually have multiple heterogeneous services (vLLM, PostgreSQL, Redis, vector DB, etc.) — when working on one service, everything related to it lives in one place instead of being scattered across `routers/`, `schemas/`, and `services/` folders.

`main.py` stays minimal — its only job is to create the FastAPI app and register each service's router:

```python
from vllm_service.routes import router as vllm_router
app.include_router(vllm_router)
```

Adding a new service (e.g. Postgres) later means creating `postgres_service/` with the same three files and adding two lines to `main.py` — nothing else changes.

---

## 2. Backend Service (`vllm_service`)

- **`client.py`** — owns the LLM connection and call logic (currently an OpenAI-compatible async client pointed at vLLM). No FastAPI code lives here.
- **`routes.py`** — owns the HTTP layer only. Delegates all actual work to `client.py`.
- **`schemas.py`** — the single source of truth for request/response shapes and their default values (e.g. `temperature`, `max_tokens`). No other file duplicates these defaults.

### Async from the start

All endpoints and client functions are `async def`, and the LLM client uses `AsyncOpenAI` rather than the sync `OpenAI` client. This matters because FastAPI runs sync (`def`) endpoints in a limited thread pool — with many concurrent requests (e.g. thousands hitting the backend at once), sync blocking I/O calls would bottleneck at the thread pool size. Async endpoints combined with an async client let concurrent requests share the event loop without blocking each other during network wait time. This was verified with a controlled test: 20 concurrent 1-second calls completed in ~1 second total (not ~20 seconds), confirming true non-blocking concurrency.

---

## 3. Networking — Docker Compose Debugging

A significant debugging session centered on a `502 Bad Gateway` error when the backend tried to reach vLLM.

**Root cause:** the backend's `.env` had `BASE_URL=http://localhost:8000/v1`. Inside a Docker container, `localhost` refers to the container itself, not the host machine or a sibling container. Since the backend and vLLM run in separate containers, `localhost` never reached vLLM.

**Fix:** changed `BASE_URL` to use the Compose service name instead of `localhost`:
```
BASE_URL=http://vllm-server:8000/v1
```
Docker Compose's internal DNS resolves service names to the correct container IP as long as both services share the same Compose file (and therefore the same default network). This was confirmed by inspecting the network (`docker network inspect`) and seeing both containers listed with valid internal IPs.

A second, unrelated bug was also found and fixed during this process: a stray indentation error in `routes.py` had silently kept a route from being registered at all, which produced confusing symptoms that initially looked network-related.

---

## 4. Standalone Terminal Client (`chat_client.py`)

A simple script for manually testing the backend from a terminal, independent of any frontend.

- Sends user input to the backend's `/chat/stream` endpoint and keeps the conversation going in a loop until the user types `exit`/`quit` or presses Ctrl+C.
- Maintains conversation history locally so multi-turn context is preserved across turns.
- Parses the backend's Server-Sent Events (SSE) response format (`data: <chunk>\n\n`) and prints tokens live as they arrive, rather than waiting for the full response — this required switching from `response.json()` (which only works for a single JSON payload) to `requests.post(..., stream=True)` with line-by-line SSE parsing.
- Deliberately does **not** send `temperature` or `max_tokens` in its request payload. Model-behavior parameters are considered a server-side concern — the backend's `schemas.py` defaults apply automatically when the client omits them. The client's only responsibility is the user's message.

---

## 5. Removing Duplicate Defaults

Early versions of the code had `temperature: float = 0.7` and `max_tokens: int = 512` duplicated in up to four places: `schemas.py`, both functions in `client.py`, and hardcoded in `chat_client.py`. This was cleaned up so that:

- **`schemas.py`** is the only place a default value is defined for the backend API.
- **`client.py`** functions now require these as explicit parameters with no defaults — they always receive an explicit value from the caller (`routes.py`), so there is no way for a stale duplicate value to silently diverge from the schema's default.
- **`chat_client.py`** no longer sends these fields at all, per the reasoning in section 4.

---

## 6. Observability — Self-Hosted Langfuse

Langfuse was added to capture prompt/response pairs, token usage, latency, and cost for every LLM call, without adding manual logging code throughout the codebase.

### Why self-hosted, and why it's a 6-container stack

Langfuse v3's self-hosted deployment separates concerns across multiple specialized services:

| Service | Role |
|---|---|
| PostgreSQL | Metadata (projects, users, API keys, settings) |
| ClickHouse | Trace/log data store, optimized for high-volume analytical queries |
| Redis | Queue between the API layer and the background worker, so incoming traces don't block on being written to storage |
| MinIO | Object storage for large blobs (e.g. attached media) |
| `langfuse-web` | The UI and API surface |
| `langfuse-worker` | Background processor that drains the Redis queue into ClickHouse/Postgres |

### Why each service exists — Langfuse v3's internal design

| Service | Role | Why it's necessary (in Langfuse's design) |
|---|---|---|
| **PostgreSQL** | Metadata store — users, projects, API keys, settings | This is the "control plane" — any web app needs somewhere to store its config/auth data |
| **ClickHouse** | Stores the actual traces/logs — prompts, responses, tokens, latency | This is the "data plane" — Postgres becomes slow for traces once volume reaches millions of rows, so ClickHouse (an analytics-optimized database) is used instead |
| **Redis** | Queue + cache | When a trace comes in, it isn't written to Postgres/ClickHouse immediately — it's placed on a Redis queue first, then processed by a background worker, so the actual LLM request isn't slowed down |
| **MinIO** | Stores large blobs (e.g. if images/files are also traced) | S3-like object storage — used when multimodal (image) traces are sent |
| **`langfuse-web`** | UI + API that's accessed in the browser | Frontend/API layer |
| **`langfuse-worker`** | Background processing (drains the Redis queue and writes into ClickHouse/Postgres) | Async processing engine |

This is heavier than a small project strictly needs, but it's the officially supported self-hosted architecture, and was chosen deliberately over lighter alternatives (Langfuse Cloud, a Postgres-only legacy version, or a custom logging solution) to match production-realistic tooling.

All Langfuse services were added into the same `docker-compose.yml` used by `vllm-server` and the backend, so they share the same Docker network and can reach each other by service name — following the same networking principle established in section 3.

### Integration approach

Langfuse's Python SDK offers a drop-in OpenAI client replacement, which was used instead of manual instrumentation:

```python
# before
from openai import AsyncOpenAI

# after
from langfuse.openai import AsyncOpenAI
```

Combined with an `@observe()` decorator on `run_chat` and `run_chat_stream`, this automatically captures the full trace (inputs, outputs, token usage, latency) for every LLM call with no other code changes required in `routes.py` or `schemas.py`.

This was verified to fail gracefully: when Langfuse's endpoint isn't reachable, the SDK logs a retry/export warning in the background but does not break or delay the actual chat request — confirmed by testing with no Langfuse server running.

---

## 7. Next Steps (Planned, Not Yet Implemented)

- **DeepEval integration** for automated response-quality scoring (e.g. relevance, hallucination checks).
- Running DeepEval as a **background task** (via FastAPI's `BackgroundTasks`) rather than synchronously, so evaluation doesn't add latency to the user-facing response.
- **Sampling** evaluation (e.g. ~10% of requests) rather than evaluating every request, since DeepEval itself makes an LLM call to score responses — evaluating 100% of traffic would roughly double LLM cost and compute load for limited additional signal at this project's scale.
- A dedicated `evaluation.py` module inside `vllm_service/`, keeping evaluation logic separate from the request-handling path in `routes.py`.

---

## Key Lessons Captured Along the Way

1. **Container networking:** `localhost` inside a container never refers to another container — always use the Compose service name.
2. **Single source of truth:** default values (like `temperature`) should be defined once and referenced everywhere else, not duplicated.
3. **Client vs. server responsibility:** the client should only send what it's actually responsible for (the user's message); model behavior configuration belongs to the server.
4. **Sync vs. async matters at scale:** thread-pool-bound sync endpoints will bottleneck under concurrent load; async endpoints with an async client avoid this, verified experimentally rather than assumed.
5. **Observability should be non-invasive:** Langfuse's drop-in client + decorator pattern was chosen specifically so that tracing could be added without restructuring the existing business logic.
