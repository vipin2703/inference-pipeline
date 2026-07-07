"""
vllm_service/schemas.py -- Chat related Pydantic models (sirf vLLM service ke liye).
"""

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: int = 512


class ChatResponse(BaseModel):
    response: str
