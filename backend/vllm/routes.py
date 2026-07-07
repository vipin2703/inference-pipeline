# """
# vllm_service/routes.py -- vLLM service ke saare API endpoints yahi honge.
# Business logic client.py se import hota hai, models schemas.py se.
# Naya vLLM-related endpoint add karna ho to bas yaha ek naya @router.<method> likho.
# """

# from fastapi import APIRouter, HTTPException
# from fastapi.responses import StreamingResponse

# from .client import get_health_info, run_chat, run_chat_stream
# # from .client import run_chat
# from .schemas import ChatRequest, ChatResponse

# router = APIRouter(tags=["vllm"])


# @router.get("/health")
# def health_check():
#     return get_health_info()


# @router.post("/chat", response_model=ChatResponse)
# def chat(request: ChatRequest):
#     # print("hello")
#     try:
#         messages_dicts = [m.model_dump() for m in request.messages]
#         response_text = run_chat(
#             messages_dicts,
#             temperature=request.temperature,
#             max_tokens=request.max_tokens,
#         )
#         return ChatResponse(response=response_text)
#     except Exception as e:
#         raise HTTPException(status_code=502, detail=f"LLM upstream error: {e}")


# @router.post("/chat/stream")
# def chat_stream(request: ChatRequest):
#     print("enter")
#     messages_dicts = [m.model_dump() for m in request.messages]
#     return StreamingResponse(
#         run_chat_stream(                
#             messages_dicts,
#             temperature=request.temperature,
#             max_tokens=request.max_tokens,
#         ),
#         media_type="text/event-stream",
#     )































"""
vllm_service/routes.py -- vLLM service ke saare API endpoints yahi honge.
Business logic client.py se import hota hai, models schemas.py se.
Naya vLLM-related endpoint add karna ho to bas yaha ek naya @router.<method> likho.

ASYNC: endpoints ab async def hain aur client.py ke async functions ko
await karte hain -- isse ek hi worker process me hazaaron concurrent
requests non-blocking tarike se handle ho sakti hain.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .client import get_health_info, run_chat, run_chat_stream
from .schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["vllm"])


@router.get("/health")
def health_check():
    return get_health_info()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        messages_dicts = [m.model_dump() for m in request.messages]
        response_text = await run_chat(
            messages_dicts,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return ChatResponse(response=response_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM upstream error: {e}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    print(request.messages)
    messages_dicts = [m.model_dump() for m in request.messages]
    return StreamingResponse(
        run_chat_stream(
            messages_dicts,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        ),
        media_type="text/event-stream",
    )