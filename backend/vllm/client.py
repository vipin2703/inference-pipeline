"""
vllm_service/client.py -- Local vLLM ke sath saara interaction yahi handle karega.
Sirf business logic. Koi FastAPI route yaha nahi hoga.

LANGFUSE TRACING:
  - `langfuse.openai` ka AsyncOpenAI drop-in wrapper use kar rahe hain --
    isse har LLM call (prompt, response, tokens, latency, cost) automatically
    Langfuse me trace ho jaata hai.
  - @observe() decorator function-level trace banata hai.

GUIDED DECODING (single LLM call):
  - `run_chat_structured()` EK call me answer + extracted_facts deta hai.
  - Gemma kabhi free-text JSON string ke ANDAR spaces/newlines pad karke
    max_tokens jala deta hai (disable_any_whitespace string-ke-andar nahi rukta).
  - Fix: schema me answer.maxLength + facts arrays pe maxItems — xgrammar
    length hit hote hi string band karwata hai, phir facts complete hote hain.

NOTE: temperature/max_tokens defaults schemas.py (ChatRequest) me hain.
"""

import os
import json
import logging
from langfuse import observe
from langfuse.openai import AsyncOpenAI

from .schemas import ExtractedFacts, StructuredChatOutput

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# Local vLLM config
# -----------------------------------------------------------
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")

llm_client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)

STRUCTURED_MIN_MAX_TOKENS = 1024
FACT_ARRAY_MAX_ITEMS = 8
# answer string ke andar infinite whitespace burn rokne ke liye (chars, not tokens)
ANSWER_MAX_CHARS = 2500

# Minimal guided schema (no $ref/$defs — xgrammar friendly).
# answer pehle: user-facing text; maxLength se padding stop.
# facts baad me: maxItems se array loop stop.
GUIDED_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "maxLength": ANSWER_MAX_CHARS,
        },
        "extracted_facts": {
            "type": "object",
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": FACT_ARRAY_MAX_ITEMS,
                },
                "facts_about_user": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": FACT_ARRAY_MAX_ITEMS,
                },
                "constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": FACT_ARRAY_MAX_ITEMS,
                },
            },
            "required": ["entities", "facts_about_user", "constraints"],
            "additionalProperties": False,
        },
    },
    "required": ["answer", "extracted_facts"],
    "additionalProperties": False,
}

CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Reply in the same language the user used (Hindi/Hinglish/English). "
    "Copy names and company names exactly as the user wrote them — do not misspell. "
    "When MEMORY is provided, treat it as true for this conversation and use it. "
    "Be concise and natural."
)

STRUCTURED_SYSTEM_PROMPT = (
    CHAT_SYSTEM_PROMPT
    + " "
    "You MUST reply with a single JSON object only (no markdown, no extra text). "
    "Shape: "
    '{"answer":"<your full reply>","extracted_facts":{"entities":[],"facts_about_user":[],"constraints":[]}}. '
    "Rules: "
    "(1) Put the complete reply in answer, then immediately close the string — "
    "do NOT pad answer with spaces, tabs, or newlines. "
    f"(2) extracted_facts: only from the latest user message; max {FACT_ARRAY_MAX_ITEMS} "
    "short items per array; empty arrays if none; no duplicates. "
    "(3) Finish the entire JSON (close all braces)."
)


def get_health_info() -> dict:
    return {"status": "ok", "base_url": BASE_URL, "model": MODEL_NAME}


def _format_memory_block(memory: dict | ExtractedFacts | None) -> str:
    if not memory:
        return ""
    if isinstance(memory, ExtractedFacts):
        data = memory.model_dump()
    else:
        data = memory
    lines: list[str] = []
    for key in ("entities", "facts_about_user", "constraints"):
        items = data.get(key) or []
        if items:
            lines.append(f"- {key}: {', '.join(str(x) for x in items)}")
    if not lines:
        return ""
    return (
        "MEMORY (facts already known from this conversation — use them; "
        "do not forget or contradict them):\n"
        + "\n".join(lines)
    )


def _with_system_and_memory(
    messages: list[dict],
    memory: dict | ExtractedFacts | None = None,
    *,
    system_prompt: str = CHAT_SYSTEM_PROMPT,
) -> list[dict]:
    """System prompt + optional persistent memory inject."""
    memory_block = _format_memory_block(memory)
    system_content = system_prompt
    if memory_block:
        system_content = f"{system_prompt}\n\n{memory_block}"

    rest = [m for m in messages if m.get("role") != "system"]
    return [{"role": "system", "content": system_content}, *rest]


def _dedupe_list(items: list, *, max_items: int = FACT_ARRAY_MAX_ITEMS) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        s = str(raw).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _normalize_structured_dict(data: dict) -> dict:
    answer = data.get("answer")
    if answer is None:
        answer = ""
    elif not isinstance(answer, str):
        answer = str(answer)
    # model trailing pad ho to clean
    answer = answer.strip()

    facts_raw = data.get("extracted_facts") or {}
    if not isinstance(facts_raw, dict):
        facts_raw = {}

    return {
        "answer": answer,
        "extracted_facts": {
            "entities": _dedupe_list(facts_raw.get("entities") or []),
            "facts_about_user": _dedupe_list(facts_raw.get("facts_about_user") or []),
            "constraints": _dedupe_list(facts_raw.get("constraints") or []),
        },
    }


def _extract_answer_from_broken_json(text: str) -> str:
    key = '"answer"'
    idx = text.find(key)
    if idx < 0:
        return ""
    after = text[idx + len(key) :]
    colon = after.find(":")
    if colon < 0:
        return ""
    after = after[colon + 1 :].lstrip()
    if not after.startswith('"'):
        return ""
    i = 1
    chars: list[str] = []
    while i < len(after):
        c = after[i]
        if c == "\\" and i + 1 < len(after):
            chars.append(after[i : i + 2])
            i += 2
            continue
        if c == '"':
            break
        chars.append(c)
        i += 1
    try:
        return json.loads('"' + "".join(chars).replace("\n", "\\n") + '"').strip()
    except json.JSONDecodeError:
        return "".join(chars).strip()


def _try_repair_truncated_json(text: str) -> dict | None:
    """Safety net agar finish_reason=length mid-JSON cut kare."""
    answer = _extract_answer_from_broken_json(text)

    candidate = text.rstrip()
    in_string = False
    escape = False
    for ch in candidate:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        candidate += '"'

    candidate = candidate.rstrip()
    if candidate.endswith(","):
        candidate = candidate[:-1]

    opens = candidate.count("{") - candidate.count("}")
    opens_arr = candidate.count("[") - candidate.count("]")
    if opens >= 0 and opens_arr >= 0:
        candidate += "]" * opens_arr + "}" * opens
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                if not (data.get("answer") or "").strip() and answer:
                    data["answer"] = answer
                if "extracted_facts" not in data or not isinstance(
                    data.get("extracted_facts"), dict
                ):
                    data["extracted_facts"] = {
                        "entities": [],
                        "facts_about_user": [],
                        "constraints": [],
                    }
                return data
        except json.JSONDecodeError:
            pass

    if answer:
        return {
            "answer": answer,
            "extracted_facts": {
                "entities": [],
                "facts_about_user": [],
                "constraints": [],
            },
        }
    return None


def _parse_structured_output(
    raw: str, finish_reason: str | None, max_tokens: int
) -> StructuredChatOutput:
    text = (raw or "").strip()
    if not text:
        raise ValueError(
            f"Empty structured output (finish_reason={finish_reason!r}, max_tokens={max_tokens})"
        )

    if "```" in text:
        start = text.find("```")
        rest = text[start + 3 :]
        if rest.lstrip().lower().startswith("json"):
            rest = rest.lstrip()[4:]
        end = rest.find("```")
        text = (rest[:end] if end >= 0 else rest).strip()

    data: dict | None = None
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Structured output root must be object, got {type(parsed).__name__}"
            )
        data = parsed
    except json.JSONDecodeError as e:
        repaired = _try_repair_truncated_json(text)
        if repaired is not None and (repaired.get("answer") or "").strip():
            logger.warning(
                "Structured JSON incomplete (finish_reason=%r); salvaged. err=%s",
                finish_reason,
                e,
            )
            data = repaired
        else:
            snippet = text[:240].replace("\n", "\\n")
            hint = ""
            if finish_reason == "length":
                hint = " Generation hit max_tokens mid-JSON."
            raise ValueError(
                f"Invalid structured JSON (finish_reason={finish_reason!r}, "
                f"max_tokens={max_tokens}, len={len(text)}).{hint} "
                f"Snippet: {snippet!r}. Error: {e}"
            ) from e

    assert data is not None
    return StructuredChatOutput(**_normalize_structured_dict(data))


@observe()
async def run_chat(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    memory: dict | ExtractedFacts | None = None,
) -> str:
    """Non-streaming plain text chat (no structured decoding)."""
    final_messages = _with_system_and_memory(
        messages, memory=memory, system_prompt=CHAT_SYSTEM_PROMPT
    )

    completion = await llm_client.chat.completions.create(
        model=MODEL_NAME,
        messages=final_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = completion.choices[0].message.content
    return (content or "").strip()


@observe()
async def run_chat_structured(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    memory: dict | ExtractedFacts | None = None,
) -> StructuredChatOutput:
    """
    EK HI LLM call + vLLM guided JSON.

    Output:
      {
        "answer": "...",                 # maxLength capped in grammar
        "extracted_facts": {
          "entities": [...],             # maxItems 8
          "facts_about_user": [...],
          "constraints": [...]
        }
      }
    """
    structured_temperature = min(temperature, 0.5)
    structured_max_tokens = max(max_tokens, STRUCTURED_MIN_MAX_TOKENS)

    final_messages = _with_system_and_memory(
        messages,
        memory=memory,
        system_prompt=STRUCTURED_SYSTEM_PROMPT,
    )
    print("strucure")
    print(final_messages)
    print("endstructure")

    completion = await llm_client.chat.completions.create(
        model=MODEL_NAME,
        messages=final_messages,
        temperature=structured_temperature,
        max_tokens=structured_max_tokens,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "structured_chat_output",
                "schema": GUIDED_JSON_SCHEMA,
                "strict": True,
            },
        },
        extra_body={
            "structured_outputs": {
                "json": GUIDED_JSON_SCHEMA,
                "disable_any_whitespace": True,
                "disable_additional_properties": True,
                "whitespace_pattern": "",
            },
        },
    )
    print(completion)
    choice = completion.choices[0]
    raw = choice.message.content or ""
    finish_reason = choice.finish_reason

    result = _parse_structured_output(raw, finish_reason, structured_max_tokens)
    if finish_reason == "length":
        logger.warning(
            "Structured hit max_tokens=%s; answer_len=%s facts=%s",
            structured_max_tokens,
            len(result.answer or ""),
            result.extracted_facts.model_dump(),
        )
    return result


@observe()
async def run_chat_stream(messages: list[dict], temperature: float, max_tokens: int):
    """Streaming plain text (no guided JSON)."""
    final_messages = _with_system_and_memory(
        messages, memory=None, system_prompt=CHAT_SYSTEM_PROMPT
    )
    try:
        stream = await llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=final_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield f"data: {delta}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: [ERROR] {e}\n\n"
