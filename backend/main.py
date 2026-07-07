"""
backend/main.py -- Sirf FastAPI app init, middleware, aur har service ka router include.

Naya service (jaise postgres, redis, vector_db) add karna ho to:
  1. backend/<service>_service/ folder banao
  2. Usme client.py (business logic) + schemas.py (models) + routes.py (endpoints) banao
  3. Yaha neeche import karke app.include_router(<service>.router, prefix="/...") add karo

Is file ka size kabhi nahi badhega, chahe 5 service ho ya 50.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from vllm.routes import router as vllm_router

# from vllm_service.routes import router as vllm_router
# naye services aayenge to yaha aur import honge, jaise:
# from postgres_service.routes import router as postgres_router
# from redis_service.routes import router as redis_router

app = FastAPI(title="LLM Backend Proxy - Local vLLM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vllm_router)
# naye services yaha include honge, jaise:
# app.include_router(postgres_router, prefix="/db")
# app.include_router(redis_router, prefix="/cache")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
