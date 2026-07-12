# Local LLM Stack

Local Docker stack: **chat client → FastAPI backend → vLLM (GPU) → model**, with **Langfuse** tracing.

---

## 1. Architecture (big picture)

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  HOST                                                                          │
│                                                                                │
│  ┌────────────────┐   :5000    ┌──────────────────┐   :8000/v1  ┌───────────┐  │
│  │ chat_client.py │ ─────────► │ backend          │ ──────────► │ vLLM      │  │
│  │ messages+facts │ ◄───────── │ llm_serve :5000  │ ◄────────── │ GPU :8000 │  │
│  └────────────────┘  answer +  └────────┬─────────┘             └───────────┘  │
│                       facts             │ traces (async)                       │
│                                         ▼                                      │
│                              ┌──────────────────────┐                          │
│                              │ langfuse-web :3000   │  UI + API                │
│                              └──────────┬───────────┘                          │
│                                         │ enqueue                              │
│                                         ▼                                      │
│                              ┌──────────────────────┐                          │
│                              │ Redis :6379          │  queue                   │
│                              └──────────┬───────────┘                          │
│                                         │ drain                                │
│                                         ▼                                      │
│                              ┌──────────────────────┐                          │
│                              │ langfuse-worker      │  :3030                   │
│                              │ Redis → storage      │                          │
│                              └──────────┬───────────┘                          │
│                    ┌────────────────────┼────────────────────┐                 │
│                    ▼                    ▼                    ▼                 │
│           ┌──────────────┐    ┌──────────────┐    ┌──────────────┐             │
│           │ ClickHouse   │    │ Postgres     │    │ MinIO        │             │
│           │ :8123 / :9000│    │ :5433→5432   │    │ :9090→9000   │             │
│           │ (traces)     │    │ (meta/users) │    │ (blobs)      │             │
│           └──────────────┘    └──────────────┘    └──────────────┘             │
└────────────────────────────────────────────────────────────────────────────────┘
```

| Service | Host port | Job |
|---------|-----------|-----|
| `chat_client.py` | — | Terminal chat, history + facts memory |
| `backend` (`llm_serve`) | **5000** | FastAPI: routes, memory inject, structured proxy |
| `vllm-server` | **8000** | Model serve + guided JSON (xgrammar) |
| `langfuse-web` | **3000** | Langfuse UI + ingest API |
| `langfuse-worker` | **3030** | Redis se traces uthata hai → ClickHouse/Postgres/MinIO |
| `Redis` | **6379** | Trace queue (localhost only) |
| `ClickHouse` | **8123** (HTTP), **9000** (native) | Trace/log store (localhost only) |
| `Postgres` | **5433** → container 5432 | Users, projects, API keys (localhost only) |
| `MinIO` | **9090** → container 9000 | Object storage for media/events |

---

## 2. Run (4 steps)

1. Env: `config/.env.example` → `config/.env` · `backend/vllm/.env.example` → `backend/vllm/.env` · model path + secrets set karo  
2. Start: `cd config` → `docker compose up -d --build`  
3. Wait: GPU + vLLM model load  
4. Chat: root se `python chat_client.py`  
   - `facts` = memory · `clear` = wipe · `exit` = quit  

| Service | URL / port |
|---------|------------|
| Backend | http://localhost:5000 |
| vLLM | http://localhost:8000 |
| Langfuse UI | http://localhost:3000 |
| Langfuse worker | http://127.0.0.1:3030 |
| Redis | 127.0.0.1:6379 |
| ClickHouse HTTP | http://127.0.0.1:8123 |
| ClickHouse native | 127.0.0.1:9000 |
| Postgres | 127.0.0.1:5433 |
| MinIO | http://localhost:9090 |

---

## 3. Request flow (one chat turn)

```
 You type message
        │
        ▼
┌───────────────────────────────────┐
│ 1. chat_client.py                 │
│    · user msg → messages[]        │
│    · payload = messages + memory  │
│    · POST /chat/structured        │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│ 2. routes.py                      │
│    · validate ChatRequest         │
│    · call run_chat_structured()   │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│ 3. client.py                      │
│    · system prompt + MEMORY block │
│    · guided JSON schema           │
│      { answer, extracted_facts }  │
│    · AsyncOpenAI → vLLM           │
│    · @observe → Langfuse (side)   │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│ 4. vLLM (GPU)                     │
│    · 1 generation (single call)   │
│    · answer + entities / facts /  │
│      constraints (schema-forced)  │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│ 5. Response back                  │
│    backend → client               │
│    · print answer                 │
│    · merge extracted_facts        │
│      into local memory            │
│    · next turn: memory re-sent    │
└───────────────────────────────────┘
```

**Memory loop:** turn N ke facts → client store → turn N+1 ke system prompt me inject → model yaad rakhta hai.

---

## 4. Backend internal flow

```
main.py
  └── include_router(vllm)
        │
        ├── schemas.py     shape + defaults (temperature, max_tokens, memory)
        ├── routes.py      HTTP only — no LLM logic
        │     /health
        │     /chat              → plain text
        │     /chat/structured   → answer + extracted_facts   ★ main path
        │     /chat/stream       → SSE tokens
        └── client.py      business logic only
              run_chat()
              run_chat_structured()   ← guided decoding, 1 LLM call
              run_chat_stream()
```

**Design:** feature slice — `vllm/` me routes + client + schemas ek saath. Naya service = naya folder + `main.py` me router.

---

## 5. Structured output (1 LLM call)

```
                    ┌─────────────────────────────┐
  user + memory ──► │  vLLM guided JSON (xgrammar) │
                    │                             │
                    │  {                          │
                    │    "answer": "...",         │  ← user-facing reply
                    │    "extracted_facts": {     │
                    │      "entities": [],        │  ← max 8
                    │      "facts_about_user": [],│
                    │      "constraints": []      │
                    │    }                        │
                    │  }                          │
                    └─────────────────────────────┘
```

`answer.maxLength` + array `maxItems` → model pad / infinite list se tokens waste na kare.

---

## 6. Langfuse flow (side path — chat block nahi karta)

```
client.py  (langfuse.openai + @observe)
    │  async export  →  http://langfuse-web:3000  (Docker network)
    ▼
langfuse-web :3000
    │  enqueue
    ▼
Redis :6379
    │  drain
    ▼
langfuse-worker :3030
    │
    ├──► ClickHouse :8123 / :9000   traces (prompt, response, tokens, latency)
    ├──► Postgres   :5433→5432      users / projects / keys
    └──► MinIO      :9090→9000      blobs / media
```

| Step | Service | Port | Kya hota hai |
|------|---------|------|----------------|
| 1 | backend SDK | — | har LLM call pe trace bhejta hai |
| 2 | `langfuse-web` | **3000** | receive + UI |
| 3 | `Redis` | **6379** | queue buffer |
| 4 | `langfuse-worker` | **3030** | Redis se uthake storage me likhta hai |
| 5 | ClickHouse / Postgres / MinIO | **8123**, **9000**, **5433**, **9090** | permanent store |

Langfuse down ho to chat ab bhi chalta hai; sirf traces miss ho sakte hain.

---

## 7. Project structure

```
rag/
├── config/
│   ├── .env.example           # template → copy to .env
│   ├── .env                   # vLLM model path, GPU, Langfuse secrets
│   ├── docker-compose.yml     # vllm-server + backend + Langfuse stack
│   └── Dockerfile
│
├── backend/
│   ├── Dockerfile
│   ├── main.py                # FastAPI app + router only
│   ├── requirements.txt
│   └── vllm/
│       ├── .env.example       # template → copy to .env
│       ├── .env               # BASE_URL, MODEL_NAME, Langfuse keys
│       ├── client.py          # LLM + structured decode + traces
│       ├── routes.py          # /health, /chat, /chat/structured, /chat/stream
│       └── schemas.py         # request / response models
│
├── chat_client.py             # terminal UI + local fact memory
└── README.md
```
