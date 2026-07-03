"""
Orders API — Idempotency + Cursor Pagination + Per-client Rate Limiting.

Assigned values:
    T (total orders) = 43
    R (rate limit)   = 15 requests / 10 seconds
"""

import time
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---- Your assigned values ----
TOTAL_ORDERS = 43           # T  -> catalog IDs are 1..43
RATE_LIMIT = 15             # R  -> 15 requests allowed
WINDOW_SECONDS = 10         # per 10-second window

app = FastAPI()

# CORS: let the grader's browser page call us from any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# ---- In-memory storage ----
idempotency_store: dict[str, dict] = {}
rate_buckets: dict[str, list[float]] = {}


# =========================================================
# 3. PER-CLIENT RATE LIMITING
# =========================================================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    # Never rate-limit CORS preflight requests — they must always succeed.
    if request.method == "OPTIONS":
        return await call_next(request)

    # Only rate-limit requests that actually carry a client id.
    if client_id:
        now = time.time()
        recent = [t for t in rate_buckets.get(client_id, []) if now - t < WINDOW_SECONDS]

        if len(recent) >= RATE_LIMIT:
            retry_after = int(WINDOW_SECONDS - (now - recent[0])) + 1
            rate_buckets[client_id] = recent
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        recent.append(now)
        rate_buckets[client_id] = recent

    return await call_next(request)


# =========================================================
# 1. IDEMPOTENT ORDER CREATION
# =========================================================
@app.post("/orders")
async def create_order(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if idempotency_key and idempotency_key in idempotency_store:
        return JSONResponse(status_code=200, content=idempotency_store[idempotency_key])

    order = {"id": str(uuid.uuid4()), "status": "created"}
    if idempotency_key:
        idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


# =========================================================
# 2. CURSOR PAGINATION
# =========================================================
@app.get("/orders")
async def list_orders(limit: int = 10, cursor: str | None = None):
    start = int(cursor) if cursor else 1
    end = min(start + limit, TOTAL_ORDERS + 1)
    items = [{"id": i, "status": "created"} for i in range(start, end)]
    next_cursor = str(end) if end <= TOTAL_ORDERS else None
    return {"items": items, "next_cursor": next_cursor}


@app.get("/")
async def root():
    return {"ok": True, "total": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}
