"""
Q9 — API Engineering: Idempotency + Cursor Pagination + Per-client Rate Limiting.

Assigned values:
    T (total orders) = 43
    R (rate limit)   = 15 requests / 10 seconds
"""

import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---- Assigned values ----
TOTAL_ORDERS = 43       # T -> catalog IDs are 1..43
RATE_LIMIT = 15         # R -> 15 requests allowed
WINDOW_SECONDS = 10     # per 10-second window

app = FastAPI()

# CORS: allow the grader's browser page to call us from any origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# ---- In-memory state (no Redis needed) ----
idempotency_store: dict[str, str] = {}        # idempotency-key -> order id
rate_buckets: dict[str, list[float]] = defaultdict(list)  # client-id -> timestamps


# =========================================================
# 3. PER-CLIENT RATE LIMITING (runs before every request)
# =========================================================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Never rate-limit CORS preflight requests.
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id")

    # Only rate-limit requests that carry a client id. Requests with no
    # X-Client-Id (e.g. a connectivity probe) are never limited.
    if client_id:
        now = time.time()
        recent = [t for t in rate_buckets[client_id] if now - t < WINDOW_SECONDS]

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
    # Repeat call with the same key -> return the SAME order id (no duplicate).
    if idempotency_key and idempotency_key in idempotency_store:
        return JSONResponse(status_code=200, content={"id": idempotency_store[idempotency_key]})

    order_id = str(uuid.uuid4())
    if idempotency_key:
        idempotency_store[idempotency_key] = order_id

    return JSONResponse(status_code=201, content={"id": order_id})


# =========================================================
# 2. CURSOR PAGINATION
# =========================================================
@app.get("/orders")
async def list_orders(limit: int = 10, cursor: str | None = None):
    # cursor is an opaque index into IDs 1..TOTAL_ORDERS; empty/None = start.
    start_idx = int(cursor) if cursor and cursor.isdigit() else 0
    end_idx = start_idx + limit

    all_ids = list(range(1, TOTAL_ORDERS + 1))
    page = all_ids[start_idx:end_idx]
    items = [{"id": i} for i in page]

    next_cursor = str(end_idx) if end_idx < TOTAL_ORDERS else None
    return {"items": items, "next_cursor": next_cursor}


@app.get("/")
async def root():
    return {"ok": True, "total": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}
