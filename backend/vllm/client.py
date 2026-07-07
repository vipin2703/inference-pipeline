# """
# vllm_service/client.py -- Local vLLM ke sath saara interaction yahi handle karega.
# Sirf business logic. Koi FastAPI route yaha nahi hoga.

# NOTE: temperature/max_tokens ki default value sirf schemas.py (ChatRequest)
# me hai -- yahi single source of truth hai. Ye functions hamesha explicit
# value expect karte hain jo routes.py se aati hai, koi duplicate default
# yaha nahi rakha taaki dono jagah value mismatch na ho sake.
# """

# import os
# from openai import OpenAI

# try:
#     from dotenv import load_dotenv
#     load_dotenv()
# except ImportError:
#     pass

# # -----------------------------------------------------------
# # Local vLLM config -- seedha localhost:8000 pe already chal
# # raha vLLM server hit karega.
# # -----------------------------------------------------------
# BASE_URL = os.getenv("BASE_URL")
# API_KEY = os.getenv("API_KEY")
# MODEL_NAME = os.getenv("MODEL_NAME")

# llm_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# def get_health_info() -> dict:
#     return {"status": "ok", "base_url": BASE_URL, "model": MODEL_NAME}


# def run_chat(messages: list[dict], temperature: float, max_tokens: int) -> str:
#     """Non-streaming chat completion. messages = list of {"role", "content"} dicts."""
#     completion = llm_client.chat.completions.create(
#         model=MODEL_NAME,
#         messages=messages,
#         temperature=temperature,
#         max_tokens=max_tokens,
#     )
#     return completion.choices[0].message.content


# def run_chat_stream(messages: list[dict], temperature: float, max_tokens: int):
#     """Streaming chat completion generator. Yields SSE-formatted string chunks."""
#     print("enter2")
#     try:
#         stream = llm_client.chat.completions.create(
#             model=MODEL_NAME,
#             messages=messages,
#             temperature=temperature,
#             max_tokens=max_tokens,
#             stream=True,
#         )
#         for chunk in stream:
#             delta = chunk.choices[0].delta.content
#             if delta:
#                 yield f"data: {delta}\n\n"
#         yield "data: [DONE]\n\n"
#     except Exception as e:
#         yield f"data: [ERROR] {e}\n\n"






























"""
vllm_service/client.py -- Local vLLM ke sath saara interaction yahi handle karega.
Sirf business logic. Koi FastAPI route yaha nahi hoga.

ASYNC: AsyncOpenAI use kar rahe hain taaki concurrent requests
(jaise 50000 ek sath) FastAPI ke event loop ko block na karein.
Har request ka network I/O wait non-blocking hota hai, isliye
thread pool bottleneck nahi hota jaisa sync client me hota tha.
"""

import os
from openai import AsyncOpenAI

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# -----------------------------------------------------------
# Local vLLM config -- seedha localhost:8000 pe already chal
# raha vLLM server hit karega.
# -----------------------------------------------------------
BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")

llm_client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)


def get_health_info() -> dict:
    return {"status": "ok", "base_url": BASE_URL, "model": MODEL_NAME}


async def run_chat(messages: list[dict], temperature: float, max_tokens: int) -> str:
    """Non-streaming chat completion. messages = list of {"role", "content"} dicts."""
    completion = await llm_client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return completion.choices[0].message.content


async def run_chat_stream(messages: list[dict], temperature: float, max_tokens: int):
    """Streaming chat completion generator. Yields SSE-formatted string chunks."""
    try:
        stream = await llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield f"data: {delta}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield f"data: [ERROR] {e}\n\n"