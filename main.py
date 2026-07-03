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
RATE_LIMIT = 15             # R  -> 15 requests allowed per window
WINDOW_SECONDS = 10         # 10-second window

app = FastAPI()

# ---- In-memory storage ----
# idempotency_store maps: idempotency-key -> the order dict we already created
idempotency_store: dict[str, dict] = {}

# rate_buckets maps: client-id -> list of timestamps of recent requests
rate_buckets: dict[str, list[float]] = {}


# =========================================================
# 3. PER-CLIENT RATE LIMITING (Middleware 1)
# =========================================================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id")

    # Only rate-limit requests that actually carry a client id header.
    if client_id:
        now = time.time()
        # Keep only timestamps that are still inside the 10-second window
        recent = [t for t in rate_buckets.get(client_id, []) if now - t < WINDOW_SECONDS]

        if len(recent) >= RATE_LIMIT:
            # Calculate retry time: oldest request in window decides when a slot frees up
            retry_after = int(WINDOW_SECONDS - (now - recent[0])) + 1
            rate_buckets[client_id] = recent
            
            # Return 429 response directly.
            # Because CORS middleware is added AFTER this middleware, CORS is the outermost layer.
            # So this response will go back through CORS middleware and get proper CORS headers!
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

        recent.append(now)
        rate_buckets[client_id] = recent

    return await call_next(request)


# =========================================================
# CORS MIDDLEWARE (Must be added LAST to be the OUTERMOST layer)
# =========================================================
# FastAPI/Starlette processes middlewares in reverse order of definition.
# The last middleware added is the first to receive incoming requests,
# and the last to process outgoing responses.
# By adding CORSMiddleware here, we guarantee that even if the rate limiter
# returns a 429 response directly, the CORS headers will still be appended.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)


# =========================================================
# 1. IDEMPOTENT ORDER CREATION
# =========================================================
@app.post("/orders")
async def create_order(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    # If no key is provided, create the order but do not cache it.
    if not idempotency_key:
        order = {"id": str(uuid.uuid4()), "status": "created"}
        return JSONResponse(status_code=201, content=order)

    # If we've seen this key, return the EXACT SAME order (status code 200, no duplicate).
    if idempotency_key in idempotency_store:
        return JSONResponse(status_code=200, content=idempotency_store[idempotency_key])

    # Otherwise, create a brand-new order.
    order = {"id": str(uuid.uuid4()), "status": "created"}
    idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


# =========================================================
# 2. CURSOR PAGINATION
# =========================================================
@app.get("/orders")
async def list_orders(limit: int = 10, cursor: str | None = None):
    # Robustly parse the cursor. Default to starting at ID 1.
    try:
        start = int(cursor) if (cursor and cursor.strip().isdigit()) else 1
        if start < 1:
            start = 1
    except (ValueError, TypeError):
        start = 1

    # Grab up to `limit` IDs, never going past TOTAL_ORDERS.
    end = min(start + limit, TOTAL_ORDERS + 1)
    items = [{"id": i, "status": "created"} for i in range(start, end)]

    # If more IDs remain, return the next starting ID as the cursor. Otherwise, return None.
    next_cursor = str(end) if end <= TOTAL_ORDERS else None

    return {"items": items, "next_cursor": next_cursor}


@app.get("/")
async def root():
    return {"ok": True, "total": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}