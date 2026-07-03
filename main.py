"""
Orders API — Idempotency + Cursor Pagination + Per-client Rate Limiting.

Assigned values:
    T (total orders) = 43
    R (rate limit)   = 15 requests / 10 seconds
"""

import time
import uuid

from fastapi import FastAPI, Header, Request, Response
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

# ---- In-memory storage (fine for this assignment) ----
# idempotency_store maps: idempotency-key -> the order dict we already created
idempotency_store: dict[str, dict] = {}

# rate_buckets maps: client-id -> list of timestamps of recent requests
rate_buckets: dict[str, list[float]] = {}


# =========================================================
# 3. PER-CLIENT RATE LIMITING (runs before every request)
# =========================================================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    # Only rate-limit requests that actually carry a client id.
    if client_id:
        now = time.time()
        # keep only timestamps still inside the 10s window
        recent = [t for t in rate_buckets.get(client_id, []) if now - t < WINDOW_SECONDS]

        if len(recent) >= RATE_LIMIT:
            # oldest request in window decides when a slot frees up
            retry_after = int(WINDOW_SECONDS - (now - recent[0])) + 1
            rate_buckets[client_id] = recent
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        recent.append(now)
        rate_buckets[client_id] = recent

    return await call_next(request)


# =========================================================
# 1. IDEMPOTENT ORDER CREATION
# =========================================================
@app.post("/orders")
async def create_order(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    # If we've seen this key, return the SAME order (HTTP 200, no duplicate).
    if idempotency_key and idempotency_key in idempotency_store:
        return JSONResponse(status_code=200, content=idempotency_store[idempotency_key])

    # Otherwise create a brand-new order.
    order = {"id": str(uuid.uuid4()), "status": "created"}

    if idempotency_key:
        idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


# =========================================================
# 2. CURSOR PAGINATION
# =========================================================
@app.get("/orders")
async def list_orders(limit: int = 10, cursor: str | None = None):
    # cursor = the next ID to start from. Empty/None means start at 1.
    start = int(cursor) if cursor else 1

    # Grab up to `limit` IDs, never going past TOTAL_ORDERS.
    end = min(start + limit, TOTAL_ORDERS + 1)
    items = [{"id": i, "status": "created"} for i in range(start, end)]

    # If more IDs remain, hand back the next starting ID as the cursor.
    next_cursor = str(end) if end <= TOTAL_ORDERS else None

    return {"items": items, "next_cursor": next_cursor}


@app.get("/")
async def root():
    return {"ok": True, "total": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}