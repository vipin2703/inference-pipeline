"""
vllm_service/schemas.py -- Chat related Pydantic models (sirf vLLM service ke liye).
"""

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class ExtractedFacts(BaseModel):
    # max_length on list = max items (Pydantic v2); keeps API output bounded
    entities: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Names, companies, products, tools mentioned (max 8)",
    )
    facts_about_user: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Personal/background info about the user (max 8)",
    )
    constraints: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Limitations or boundaries stated (max 8)",
    )


class ChatRequest(BaseModel):
    messages: list[Message]
    temperature: float = 0.7
    # max_tokens = model kitne NEW tokens generate kar sakta hai (print limit nahi).
    # Client full answer print karta hai; agar generation beech me rukti hai to yeh budget khatam hua.
    # vLLM MAX_MODEL_LEN se bada mat rakhna (prompt + completion dono usme aate hain).
    max_tokens: int = 2048
    # Client-side persistent memory -- har turn model ke system prompt me inject hota hai
    memory: ExtractedFacts | None = None


class ChatResponse(BaseModel):
    response: str


class StructuredChatOutput(BaseModel):
    answer: str
    extracted_facts: ExtractedFacts


