# ============================================================
# Dockerfile  (client_/ folder me rakho)
# ------------------------------------------------------------
# NOTE: python:3.14t-slim (free-threaded/no-GIL tag) Docker Hub
# ki OFFICIAL image me abhi exist NAHI karta -- verify kiya,
# community isko maang rahi h (GitHub issue #1082 docker-library
# /python repo me) lekin abhi release nahi hua.
#
# Isliye normal "python:3.14-slim" use kar rahe h (GIL wala
# build). Ye client ke liye koi farak nahi padta kyunki ye
# sirf HTTP calls (network I/O) kar raha h -- free-threading
# ka fayda CPU-bound multi-threaded workloads me milta h,
# jaisa tera local inference setup (llama.cpp) hai, is halke
# client script me nahi.
# ============================================================

FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]

# ============================================================
# BUILD karne ka command (isi client_/ folder ke andar se):
#   docker build -t my-rag-client .
#
# RUN karne ka command:
#   docker run --env-file .env my-rag-client
# ============================================================