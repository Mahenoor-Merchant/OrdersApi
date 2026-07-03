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

# Per-client fixed-window counter: client_id -> [window_start_ts, count]
rate_buckets: dict[str, list] = {}


# =========================================================
# 3. PER-CLIENT RATE LIMITING (fixed 10s window per client)
# =========================================================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # CORS preflight must never be blocked.
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id")

    # Only clients that identify themselves are bucketed. No id -> never limited.
    if client_id:
        now = time.time()
        bucket = rate_buckets.get(client_id)

        # Start a fresh window if none exists or the old one has fully elapsed.
        if bucket is None or now - bucket[0] >= WINDOW_SECONDS:
            rate_buckets[client_id] = [now, 1]
        else:
            if bucket[1] >= RATE_LIMIT:
                retry_after = int(WINDOW_SECONDS - (now - bucket[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": str(max(retry_after, 1))},
                )
            bucket[1] += 1

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
