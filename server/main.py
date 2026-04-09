from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import or_, asc, desc, text
from typing import List, Optional, Dict, Any
import json
import uuid
import stripe
import os
from dotenv import load_dotenv
load_dotenv()
import httpx
from pydantic import BaseModel, Field
from llm_client import get_client, close_client, health as llm_health, chat as llm_chat
import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
from database import Base, engine, get_db
from models import User, Product, Order, OrderItem, OrderStatus, Payment, CartItem, UserRole
from schemas import UserCreate, UserOut, TokenOut, ProductOut, OrderCreate, OrderOut, AdminProductCreate, AddressUpdate
from auth import hash_password, verify_password, create_access_token, get_current_user
from seed import seed_products
from permission import require_roles
from schemas import GenerateDescIn
import time
import threading

# ---------- NEW imports for RAG/embeddings & parsing ----------
from functools import lru_cache
try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

import re
from math import floor, ceil
# import ast
# -------------------------------------------------------------

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ecom API", version="3.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles(UserRole.admin))]  # server-side authz
)

@app.on_event("startup")
def on_startup():
    get_client()
    db = next(get_db())
    seed_products(db)

# ---------------- AUTH ----------------
@app.post("/auth/register", response_model=UserOut)
def register(user: UserCreate, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.email == user.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    u = User(name=user.name, email=user.email, password_hash=hash_password(user.password), role=UserRole.user)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

# login route
@app.post("/auth/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user

# ---------------- PRODUCTS ----------------
def product_to_out(p: Product) -> ProductOut:
    specs = None
    if p.specs_json:
        try:
            specs = json.loads(p.specs_json)
        except:
            specs = None
    return ProductOut(
        id=p.id, name=p.name, description=p.description,
        category=p.category, price_cents=p.price_cents,
        image_url=p.image_url, stock=p.stock, specs=specs
    )

@app.get("/products", response_model=List[ProductOut])
def list_products(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    min_price_cents: Optional[int] = Query(None, ge=0),
    max_price_cents: Optional[int] = Query(None, ge=0),
    in_stock: Optional[bool] = Query(None),
    sort: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Product)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

    if category:
        query = query.filter(Product.category == category)

    if min_price_cents is not None:
        query = query.filter(Product.price_cents >= min_price_cents)
    if max_price_cents is not None:
        query = query.filter(Product.price_cents <= max_price_cents)

    if in_stock is not None:
        query = query.filter(Product.stock > 0 if in_stock else Product.stock <= 0)

    if sort == "price_asc":
        query = query.order_by(asc(Product.price_cents))
    elif sort == "price_desc":
        query = query.order_by(desc(Product.price_cents))
    elif sort == "name_asc":
        query = query.order_by(asc(Product.name))
    elif sort == "name_desc":
        query = query.order_by(desc(Product.name))

    products = query.all()
    return [product_to_out(p) for p in products]

@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_to_out(p)

# ---------------- ORDERS ----------------
@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items in order")

    total, items = 0, []
    # Validate products and calculate total
    for it in payload.items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product {it.product_id} not found")
        if prod.stock < it.quantity:
            raise HTTPException(status_code=400, detail="Insufficient stock")
        total += prod.price_cents * it.quantity
        items.append(OrderItem(product_id=prod.id, quantity=it.quantity, unit_price_cents=prod.price_cents))

    # Create the order
    order = Order(
        user_id=current_user.id,
        status=OrderStatus.PENDING_PAYMENT,
        total_amount_cents=total,
        payment_method=payload.payment_method,
        shipping_address=payload.shipping_address,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone
    )
    db.add(order)
    db.flush()  # ensures order.id exists before adding items

    # Add order items
    for it in items:
        it.order_id = order.id
        db.add(it)

    db.commit()
    db.refresh(order)
    return order

# ---------------- PAYMENTS (Stripe) ----------------
@app.post("/payments/stripe-session/{order_id}")
def create_stripe_session(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Fetch the order
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # ✅ NEW: Block Stripe session for non-stripe payment methods (e.g., COD)
    if (getattr(order, "payment_method", "") or "").lower() != "stripe":
        raise HTTPException(
            status_code=400,
            detail="Stripe session is only available for stripe-paid orders."
        )

    # Stripe minimum amount check (50 cents USD ~ 50 INR in test mode)
    MIN_AMOUNT_CENTS = 5000  # 50 INR in paise
    if order.total_amount_cents < MIN_AMOUNT_CENTS:
        print(
            f"Warning: Order total {order.total_amount_cents} paise is below Stripe minimum. "
            f"Adjusting to {MIN_AMOUNT_CENTS}."
        )
        stripe_amount = MIN_AMOUNT_CENTS
    else:
        stripe_amount = order.total_amount_cents

    # Create Stripe Checkout session
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'inr',
                'product_data': {'name': f'Order #{order.id}'},
                'unit_amount': stripe_amount
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=f"http://localhost:4200/payment-success?order_id={order.id}",
        cancel_url=f"http://localhost:4200/payment-failed?order_id={order.id}",
        metadata={'order_id': str(order.id)}
    )

    # Create payment record in DB (initially pending)
    payment = Payment(
        order_id=order.id,
        amount_cents=stripe_amount,
        status="pending",
        gateway_ref=session.id
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {"checkout_url": session.url}

@app.post("/payments/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, stripe_webhook_secret)
    except Exception as e:
        print("Webhook error:", e)
        return JSONResponse(status_code=400, content={"detail": "Invalid payload/signature"})

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print("Webhook session object:", session)

        order_id_str = session.get('metadata', {}).get('order_id')
        if not order_id_str:
            print("Webhook missing order_id")
            return JSONResponse(status_code=400, content={"detail": "Missing order_id"})

        order = db.query(Order).filter(Order.id == int(order_id_str)).first()
        if not order:
            print(f"Order {order_id_str} not found")
            return JSONResponse(status_code=404, content={"detail": "Order not found"})

        # Update payment record
        payment = db.query(Payment).filter(Payment.order_id == order.id).first()
        if payment:
            payment.status = "success"
        else:
            payment = Payment(
                order_id=order.id,
                amount_cents=order.total_amount_cents,
                status="success",
                gateway_ref=session.get("id")
            )
            db.add(payment)

        # Mark order as paid
        if order.status != OrderStatus.PAID:
            order.status = OrderStatus.PAID

        # Reduce stock
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock = max(product.stock - item.quantity, 0)

        # Clear cart
        db.query(CartItem).filter(CartItem.user_id == order.user_id).delete()

        db.commit()
        print(f"Order {order.id} marked as PAID, payment updated.")
    return {"status": "success"}

# List all orders for the current user
@app.get("/orders", response_model=List[OrderOut])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).all()
    return orders

# Get single order by ID
@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Find the order for this user
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Only allow cancellation if not paid yet
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled at this stage")

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)
    # Return a proper JSON response
    return {"status": "success", "message": f"Order {order.id} cancelled"}

# ==========================
# Admin Search - embedder & helpers (local BGE-M3)
# ==========================
ADMIN_EMBED_MODEL = os.getenv("ADMIN_EMBED_MODEL", "BAAI/bge-m3")

@lru_cache(maxsize=1)
def _get_admin_embedder():
    if SentenceTransformer is None:
        raise RuntimeError(
            "sentence-transformers is not installed in the server venv. "
            "Install it with: pip install sentence-transformers"
        )
    # Use Apple Silicon MPS if available
    device = "cpu"
    try:
        import torch
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
    except Exception:
        pass
    return SentenceTransformer(ADMIN_EMBED_MODEL, device=device)

def _embed_query(q: str) -> List[float]:
    model = _get_admin_embedder()
    vec = model.encode([q], normalize_embeddings=True)[0]
    return vec.tolist()

def _vector_literal(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"

def _make_snippet(content: str, q: Optional[str], max_len: int = 180) -> str:
    if not content:
        return ""
    if not q:
        return (content[:max_len] + "…") if len(content) > max_len else content
    low_c = content.lower()
    low_q = q.lower()
    i = low_c.find(low_q)
    if i == -1:
        return (content[:max_len] + "…") if len(content) > max_len else content
    start = max(0, i - max_len // 3)
    end = min(len(content), i + len(q) + max_len // 3)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"

# --- RRF fusion helper (hybrid vector + BM25) ---
def _rrf_fuse(
    vec_rows: List[Dict[str, Any]],
    bm_rows: List[Dict[str, Any]],
    rrf_k: int = 60
) -> List[Dict[str, Any]]:
    """
    Fuse two ranked lists using Reciprocal Rank Fusion:
      score(d) = sum(1 / (rrf_k + rank_i(d)))
    Returns a list of rows with 'rrf_score' added, sorted desc.
    """
    fused: Dict[int, Dict[str, Any]] = {}
    # vector list ranks
    for idx, r in enumerate(vec_rows, start=1):
        rid = r.get("id")
        if rid is None:
            continue
        entry = fused.setdefault(rid, {"row": dict(r), "ranks": []})
        entry["ranks"].append(("vec", idx))
    # bm25 list ranks
    for idx, r in enumerate(bm_rows, start=1):
        rid = r.get("id")
        if rid is None:
            continue
        entry = fused.setdefault(rid, {"row": dict(r), "ranks": []})
        # if a doc exists in both lists, we keep whichever row was already stored
        entry["ranks"].append(("bm25", idx))

    out: List[Dict[str, Any]] = []
    for _, data in fused.items():
        ranks = [rk for _, rk in data["ranks"]]
        rrf_score = sum(1.0 / (rrf_k + rk) for rk in ranks)
        row = data["row"]
        row["rrf_score"] = rrf_score
        out.append(row)
    out.sort(key=lambda x: x["rrf_score"], reverse=True)
    return out

# admin search (Support UI will call this)
@admin_router.get("/search")
def admin_search(
    q: Optional[str] = Query(None, description="Query text. Empty returns recent items."),
    k: int = Query(10, ge=1, le=50, description="Number of results."),
    # NEW: type filter
    type: str = Query("any", description="Filter by source: product|order|user|policy|any"),
    # existing hybrid controls (kept as-is)
    hybrid: bool = Query(False, description="Fuse vector + BM25 via RRF"),
    rrf_k: int = Query(60, ge=1, le=200, description="RRF smoothing constant (default 60)"),
    bm25_k: Optional[int] = Query(None, ge=1, le=200, description="Top-k for BM25 list (defaults to k)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin search over admin_documents with optional entity filter and hybrid (RRF).

    - 'type' narrows by source: product|order|user|policy|any (default any)
    - Vector: ORDER BY embedding <=> :qvec ASC  --> similarity = 1 - distance
    - BM25:   ts_rank_cd(tsv, websearch_to_tsquery('english', :q))
    - Hybrid: RRF fuse vector and BM25 result lists (no score normalization)
    """
    allowed_types = {"product", "order", "user", "policy", "any"}
    t = (type or "any").lower()
    if t not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Invalid type '{type}'. Use one of {sorted(allowed_types)}")

    src = None if t == "any" else t

    # --- No query -> recent items (optionally filtered) ---
    if not q or not q.strip():
        if src:
            rows = db.execute(
                text("""
                    SELECT id, source, product_id, title, content, metadata,
                           0.0 AS score
                    FROM admin_documents
                    WHERE source = :src
                    ORDER BY updated_at DESC
                    LIMIT :k
                """),
                {"k": k, "src": src}
            ).mappings().all()
        else:
            rows = db.execute(
                text("""
                    SELECT id, source, product_id, title, content, metadata,
                           0.0 AS score
                    FROM admin_documents
                    ORDER BY updated_at DESC
                    LIMIT :k
                """),
                {"k": k}
            ).mappings().all()

        items: List[Dict[str, Any]] = []
        for r in rows:
            content = r.get("content") or ""
            items.append({
                "score": round(float(r.get("score", 0.0)), 4),
                "snippet": _make_snippet(content, q),
                "source": r.get("source"),
                "product_id": r.get("product_id"),
                "title": r.get("title"),
                "metadata": r.get("metadata"),
            })
        return {"items": items, "total": len(items)}

    # --- With a query ---
    q_s = q.strip()
    qvec = _vector_literal(_embed_query(q_s))  # cosine-normalized

    # Vector top-k (with optional source filter)
    if src:
        vec_rows = db.execute(
            text("""
                SELECT id, source, product_id, title, content, metadata,
                       (1.0 - (embedding <=> CAST(:qvec AS vector))) AS vec_score
                FROM admin_documents
                WHERE source = :src
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :k
            """),
            {"qvec": qvec, "k": k, "src": src}
        ).mappings().all()
    else:
        vec_rows = db.execute(
            text("""
                SELECT id, source, product_id, title, content, metadata,
                       (1.0 - (embedding <=> CAST(:qvec AS vector))) AS vec_score
                FROM admin_documents
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :k
            """),
            {"qvec": qvec, "k": k}
        ).mappings().all()

    # Vector-only response (unchanged behavior when hybrid=false)
    if not hybrid:
        items: List[Dict[str, Any]] = []
        for r in vec_rows:
            content = r.get("content") or ""
            items.append({
                "score": round(float(r.get("vec_score", 0.0)), 4),
                "snippet": _make_snippet(content, q_s),
                "source": r.get("source"),
                "product_id": r.get("product_id"),
                "title": r.get("title"),
                "metadata": r.get("metadata"),
            })
        return {"items": items, "total": len(items)}

    # Hybrid path: BM25 top-k (apply same source filter), then RRF fuse
    bm_k = bm25_k or k
    if src:
        bm_rows = db.execute(
            text("""
                WITH q AS (SELECT websearch_to_tsquery('english', :q) AS tsq)
                SELECT d.id, d.source, d.product_id, d.title, d.content, d.metadata,
                       ts_rank_cd(d.tsv, q.tsq) AS bm25
                FROM admin_documents d, q
                WHERE d.source = :src
                  AND d.tsv @@ q.tsq
                ORDER BY bm25 DESC
                LIMIT :k
            """),
            {"q": q_s, "k": bm_k, "src": src}
        ).mappings().all()
    else:
        bm_rows = db.execute(
            text("""
                WITH q AS (SELECT websearch_to_tsquery('english', :q) AS tsq)
                SELECT d.id, d.source, d.product_id, d.title, d.content, d.metadata,
                       ts_rank_cd(d.tsv, q.tsq) AS bm25
                FROM admin_documents d, q
                WHERE d.tsv @@ q.tsq
                ORDER BY bm25 DESC
                LIMIT :k
            """),
            {"q": q_s, "k": bm_k}
        ).mappings().all()

    fused = _rrf_fuse(vec_rows, bm_rows, rrf_k=rrf_k)

    items: List[Dict[str, Any]] = []
    for r in fused[:k]:  # final cut to k
        content = r.get("content") or ""
        items.append({
            "score": round(float(r.get("rrf_score", 0.0)), 4),
            "snippet": _make_snippet(content, q_s),
            "source": r.get("source"),
            "product_id": r.get("product_id"),
            "title": r.get("title"),
            "metadata": r.get("metadata"),
        })
    return {"items": items, "total": len(items)}

# admin add product (Support UI will call this)
@admin_router.post("/products", response_model=ProductOut)
def admin_add_product(
    payload: AdminProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Create & persist
    p = Product(
        name=payload.name.strip(),
        description=payload.description.strip(),  # NOT NULL in DB
        category=(payload.category or None),
        price_cents=payload.price_cents,
        image_url=(payload.image_url or None),
        stock=payload.stock,
        specs_json=json.dumps(payload.specs) if payload.specs else None
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # Return the mapped output
    return product_to_out(p)

# ==========================
# ASM Assistant (Admin-only) — RAG + safe tool execution
# ==========================

class ASMChatIn(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)

class ASMChatOut(BaseModel):
    reply: str

# In-memory session store (dev-friendly)
_ASM_SESSIONS: Dict[str, Dict[str, Any]] = {}
_ASM_LOCK = threading.Lock()

# Quantity policy: max 2 per product line (as you requested)
_ASM_MAX_QTY_PER_PRODUCT = 2

_EMAIL_RX = re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.\w+")
_INT_RX = re.compile(r"\b(\d+)\b")
# --- Product-id extraction patterns ---
_PID_RX = re.compile(r"\b(?:product[_\s-]*id|pid)\s*[:=]?\s*(\d+)\b", re.IGNORECASE)

def _extract_product_id(text_: str) -> Optional[int]:
    """
    Extract product id from patterns like:
      - product_id 3
      - product id: 3
      - pid=3
    """
    m = _PID_RX.search(text_ or "")
    return int(m.group(1)) if m else None

def _normalize_name(s: str) -> str:
    # strict compare normalization: trim + collapse spaces + lowercase
    return " ".join((s or "").strip().split()).lower()

def _get_product_by_id(db: Session, pid: int) -> Optional[Product]:
    return db.query(Product).filter(Product.id == pid).first()

def _get_product_by_exact_name(db: Session, name: str) -> Optional[Product]:
    """
    Strict match: case-insensitive normalized equality.
    This is stricter than ILIKE.
    """
    target = _normalize_name(name)
    if not target:
        return None

    # Best effort: do a fast candidate fetch using ILIKE and then normalize compare
    # (keeps DB query cheap without needing functional indexes)
    like = f"%{name.strip()}%"
    candidates = db.query(Product).filter(Product.name.ilike(like)).all()
    for p in candidates:
        if _normalize_name(p.name) == target:
            return p
    return None

def _suggest_closest_product(db: Session, query: str) -> Optional[dict]:
    """
    Suggest (but do not auto-choose) a closest product using vector search.
    Returns dict with {product, dist} or None.
    """
    q = (query or "").strip()
    if not q:
        return None

    try:
        qvec = _vector_literal(_embed_query(q))
        row = db.execute(
            text("""
                SELECT product_id, (embedding <=> CAST(:qvec AS vector)) AS dist
                FROM admin_documents
                WHERE source='product'
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT 1
            """),
            {"qvec": qvec}
        ).mappings().first()

        if not row or not row.get("product_id"):
            return None

        pid = int(row["product_id"])
        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            return None

        return {"product": product, "dist": float(row.get("dist", 1e9))}
    except Exception:
        return None

def _is_yes(text_: str) -> bool:
    t = (text_ or "").strip().lower()
    return t in ("yes", "y", "confirm", "ok", "okay", "proceed", "use it")

def _is_no(text_: str) -> bool:
    t = (text_ or "").strip().lower()
    return t in ("no", "n", "cancel", "stop", "dont", "don't", "do not")

def _session_key(admin_id: int, session_id: str) -> str:
    return f"{admin_id}:{session_id}"

def _get_or_create_session(admin_id: int, session_id: str) -> Dict[str, Any]:
    key = _session_key(admin_id, session_id)
    with _ASM_LOCK:
        s = _ASM_SESSIONS.get(key)
        if not s:
            s = {
                "created_at": time.time(),
                "pending": None,        # e.g., "create_order"
                "data": {},             # stores collected fields
            }
            _ASM_SESSIONS[key] = s
        return s

def _clear_session(admin_id: int, session_id: str) -> None:
    key = _session_key(admin_id, session_id)
    with _ASM_LOCK:
        _ASM_SESSIONS.pop(key, None)

def _extract_email(text_: str) -> Optional[str]:
    m = _EMAIL_RX.search(text_ or "")
    return m.group(0).strip() if m else None

def _extract_qty(text_: str) -> Optional[int]:
    t = (text_ or "").lower()

    # Look for explicit quantity patterns only
    patterns = [
        r"\bqty\s*[:=]?\s*(\d+)\b",
        r"\bquantity\s*[:=]?\s*(\d+)\b",
        r"\bx\s*(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return int(m.group(1))

    # No explicit quantity provided
    return None


def _user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def _resolve_product_by_query(db: Session, query: str) -> Optional[Product]:
    """
    Resolve a product by a free-text query.
    Strategy:
      1) Exact-ish match on name (ILIKE)
      2) Fallback: try vector search against admin_documents and pick product_id
      3) Fetch Product by id
    """
    q = (query or "").strip()
    if not q:
        return None

    # 1) direct DB match
    like = f"%{q}%"
    p = db.query(Product).filter(Product.name.ilike(like)).order_by(Product.id.asc()).first()
    if p:
        return p

    # 2) fallback to vector search in admin_documents (products only)
    try:
        qvec = _vector_literal(_embed_query(q))
        row = db.execute(
            text("""
                SELECT product_id
                FROM admin_documents
                WHERE source='product'
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT 1
            """),
            {"qvec": qvec}
        ).mappings().first()
        if row and row.get("product_id"):
            pid = int(row["product_id"])
            return db.query(Product).filter(Product.id == pid).first()
    except Exception:
        pass

    return None

def _validate_qty(qty: int) -> Optional[str]:
    if qty <= 0:
        return "Quantity must be at least 1."
    if qty > _ASM_MAX_QTY_PER_PRODUCT:
        return f"Quantity exceeds policy limit. Max allowed per product is {_ASM_MAX_QTY_PER_PRODUCT}."
    return None

def _validate_stock(product: Product, qty: int) -> Optional[str]:
    if product.stock <= 0:
        return "Product is out of stock."
    if product.stock < qty:
        return f"Insufficient stock. Available: {product.stock}, requested: {qty}."
    return None

def _create_cod_order_for_user(
    db: Session,
    user: User,
    product: Product,
    qty: int,
    shipping_address: str,
    contact_name: str,
    contact_phone: str,
) -> Order:
    """
    Creates a COD order for the given user.
    NOTE: leaves status as PENDING_PAYMENT to match your current cancel behavior.
    """
    # Create order
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING_PAYMENT,
        total_amount_cents=product.price_cents * qty,
        payment_method="cod",
        shipping_address=shipping_address,
        contact_name=contact_name,
        contact_email=user.email,   # safe: sourced from user record
        contact_phone=contact_phone,
    )
    db.add(order)
    db.flush()  # obtain order.id

    # Create order item
    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=qty,
        unit_price_cents=product.price_cents
    )
    db.add(item)

    db.commit()
    db.refresh(order)
    return order

async def _ask_llm_to_extract_intent(message: str) -> Dict[str, Any]:
    """
    Ask Groq (via llm_chat) to extract a structured intent.
    Output schema:
      {
        "intent": "CREATE_ORDER" | "UNKNOWN",
        "user_email": "x@y.com" | null,
        "product_query": "..." | null,
        "quantity": number | null,
        "shipping_address": "..." | null,
        "contact_phone": "..." | null
      }
    """
    system = (
        "You are an assistant that extracts structured data for an admin support workflow. "
        "Return ONLY valid JSON. No markdown."
    )
    prompt = f"""
Extract intent and fields from the admin message for an e-commerce support system.

Admin message:
{message}

Return JSON with keys:
intent: "CREATE_ORDER" or "UNKNOWN"
user_email: string or null
product_query: string or null
quantity: number or null
shipping_address: string or null
contact_phone: string or null
"""
    data = await llm_chat(prompt=prompt, system=system, temperature=0.0, max_tokens=200)
    txt = (data.get("output") or "").strip()

    # Parse JSON safely (best-effort)
    try:
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            txt = txt[start:end+1]
        return json.loads(txt)
    except Exception:
        # fallback to simple heuristics if LLM response isn't strict JSON
        return {
            "intent": "UNKNOWN",
            "user_email": _extract_email(message),
            "product_query": None,
            "quantity": _extract_qty(message),
            "shipping_address": None,
            "contact_phone": None,
        }

@admin_router.post("/asm/chat", response_model=ASMChatOut)
async def asm_chat(
    body: ASMChatIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin-only ASM assistant endpoint (chat).
    - Multi-turn state in memory (session_id)
    - Uses LLM only for parsing/extraction and policy responses; DB writes happen server-side.
    """
    session = _get_or_create_session(current_user.id, body.session_id)
    msg = (body.message or "").strip()

    # If we are mid-flow waiting for missing details, merge and continue
    pending = session.get("pending")
    data = session.get("data", {})

    # Try to extract fields from this message
    extracted = await _ask_llm_to_extract_intent(msg)

    # Merge extracted details into session data (only fill missing)
    for key in ["user_email", "product_query", "quantity", "shipping_address", "contact_phone"]:
        val = extracted.get(key)
        if not val:
            continue

        # Always overwrite user_email and quantity when present in the new message
        if key in ("user_email", "quantity"):
            data[key] = val
            continue

        # product_query: overwrite only if message looks like it includes a product phrase,
        # otherwise keep previous (safe default)
        if key == "product_query":
            if not data.get(key):
                data[key] = val
            continue

        # for address/phone: fill missing only
        if not data.get(key):
            data[key] = val

    session["data"] = data

    # Determine intent if not already pending
    if not pending:
        if extracted.get("intent") == "CREATE_ORDER" or ("create" in msg.lower() and "order" in msg.lower()):
            session["pending"] = "create_order"
            pending = "create_order"
        else:
            # Non-action question: use policy-aware /ai/answer style response (reuse your policies via RAG)
            # Keep this simple: forward to /ai/answer logic by calling llm_chat with a policy context hint.
            # (We rely on your existing /ai/answer endpoint for general questions in UI; here just answer guidance.)
            return ASMChatOut(reply="I can help create/cancel orders. Say: 'For user <email> create order for <product> qty <n>'.")

    # ---------------------------
    # ---------------------------
    # Pending: confirm suggested product
    # ---------------------------
    if pending == "confirm_product":
        d = session.get("data", {})
        if _is_yes(msg):
            pid = d.get("suggested_product_id")
            if not pid:
                session["pending"] = "create_order"
            else:
                d["product_id"] = pid
                # clear suggestion fields
                d.pop("suggested_product_id", None)
                d.pop("suggested_product_name", None)
                session["data"] = d
                session["pending"] = "create_order"
            return ASMChatOut(reply="Confirmed. Continuing order creation—please provide quantity if not already provided.")
        if _is_no(msg):
            # Clear suggestion and return to create flow
            d.pop("suggested_product_id", None)
            d.pop("suggested_product_name", None)
            session["data"] = d
            session["pending"] = "create_order"
            return ASMChatOut(reply="Okay. Please provide the exact product name or product_id.")
        return ASMChatOut(reply="Please reply YES to confirm the suggested product, or NO to provide a different product.")

    # Pending: create_order flow
    # ---------------------------
    if pending == "create_order":
        email = data.get("user_email") or _extract_email(msg)
        if not email:
            return ASMChatOut(reply="Please provide the user's email address to create the order.")

        user = _user_by_email(db, email)
        if not user:
            # keep session but ask again
            data["user_email"] = email
            session["data"] = data
            return ASMChatOut(reply=f"Can't find a user with email '{email}'. Please check and provide a valid user email.")

        # Product query
        # -----------------------
        # Product resolution (STRICT)
        # -----------------------
        # Priority 1: explicit product_id in the message
        pid = _extract_product_id(msg)
        if pid is not None:
            product = _get_product_by_id(db, pid)
            if not product:
                return ASMChatOut(reply=f"Can't find a product with product_id={pid}. Please provide a valid product_id.")
            # store resolved product id in session
            data["product_id"] = product.id
            session["data"] = data
        else:
            # Priority 2: strict exact name match
            product_query = data.get("product_query")
            if not product_query:
                return ASMChatOut(reply="Please provide the exact product name, or provide product_id (e.g., product_id 3).")

            product = _get_product_by_exact_name(db, product_query)

            if not product:
                # Optional: suggest closest match and ask for confirmation
                suggestion = _suggest_closest_product(db, product_query)
                if suggestion and suggestion.get("product"):
                    sugg_p = suggestion["product"]
                    # Save suggested product in session and switch pending state to confirm
                    data["suggested_product_id"] = sugg_p.id
                    data["suggested_product_name"] = sugg_p.name
                    session["data"] = data
                    session["pending"] = "confirm_product"
                    return ASMChatOut(
                        reply=(
                            f"I can't find an exact product named '{product_query}'.\n"
                            f"Closest match is '{sugg_p.name}' (product_id={sugg_p.id}).\n"
                            f"Reply YES to use this product, or reply NO and provide the exact product name / product_id."
                        )
                    )
                return ASMChatOut(
                    reply=f"Can't find an exact product named '{product_query}'. Please provide the exact product name or product_id."
                )

            # store resolved product id
            data["product_id"] = product.id
            session["data"] = data


        # Ensure product object is loaded from stored product_id
        if not locals().get("product"):
            pid2 = data.get("product_id")
            if pid2:
                product = _get_product_by_id(db, int(pid2))
        if not product:
            return ASMChatOut(reply="Product is not resolved yet. Please provide exact product name or product_id.")


        # Quantity
        qty = data.get("quantity")
        if qty is None:
            return ASMChatOut(reply=f"How many units of '{product.name}' should I order? (Max {_ASM_MAX_QTY_PER_PRODUCT})")

        try:
            qty = int(qty)
        except Exception:
            return ASMChatOut(reply="Quantity must be a number. Please provide a valid quantity (1 or 2).")

        err = _validate_qty(qty)
        if err:
            return ASMChatOut(reply=err)

        err = _validate_stock(product, qty)
        if err:
            return ASMChatOut(reply=err)

        # Required fields: shipping_address, contact_phone (we can use user defaults if present)
        shipping_address = data.get("shipping_address") or getattr(user, "default_shipping_address", None)
        contact_phone = data.get("contact_phone") or getattr(user, "default_contact_phone", None)

        missing = []
        if not shipping_address:
            missing.append("shipping address")
        if not contact_phone:
            missing.append("contact phone number")

        if missing:
            need = " and ".join(missing)
            # keep pending state; ask admin to provide missing info
            session["data"] = data
            return ASMChatOut(reply=f"I need the user's {need} to create the order. Please provide it.")

        # Contact name: prefer user.name, else ask admin (rare)
        contact_name = getattr(user, "name", None) or "Customer"

        # Create COD order (pending payment)
        order = _create_cod_order_for_user(
            db=db,
            user=user,
            product=product,
            qty=qty,
            shipping_address=shipping_address,
            contact_name=contact_name,
            contact_phone=contact_phone,
        )

        # Clear session after success
        _clear_session(current_user.id, body.session_id)

        return ASMChatOut(
            reply=(
                f"Order created successfully.\n"
                f"- Order ID: {order.id}\n"
                f"- User: {user.email}\n"
                f"- Payment method: COD\n"
                f"- Status: {order.status}\n"
                f"The COD order is now visible in the user's profile."
            )
        )

    # Fallback
    return ASMChatOut(reply="I couldn't process that request. Try: 'For user <email> create order for <product> qty <1|2>'.")

@admin_router.post("/asm/users/{user_id}/orders/{order_id}/cancel")
def asm_cancel_order_for_user(
    user_id: int,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin-only: cancel a specific order for a specific customer.

    Strict checks:
    1) user exists
    2) order exists
    3) order belongs to user
    4) order is cancellable under current enforcement (PENDING_PAYMENT only)
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.user_id != user.id:
        raise HTTPException(status_code=400, detail="Order does not belong to this user")

    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled at this stage")

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)

    return {
        "status": "success",
        "message": f"Order {order.id} cancelled for user {user.id} by support"
    }


# ==========================
# ASM Assistant (Admin-only) — AI-driven CANCEL + CREATE (tool-style execution)
# ==========================

class ASMChatIn(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)

class ASMChatOut(BaseModel):
    reply: str


# In-memory session store for multi-turn flows (dev-friendly)
_ASM_SESSIONS: Dict[str, Dict[str, Any]] = {}
_ASM_LOCK = threading.Lock()

# Policy: max 2 per product line
_ASM_MAX_QTY_PER_PRODUCT = 2

# Extractors
_EMAIL_RX = re.compile(r"[\w\.\-\+]+@[\w\.\-]+\.\w+")
_ORDER_ID_RX = re.compile(r"\border\s*#?\s*(\d+)\b", re.IGNORECASE)
_PID_RX = re.compile(r"\b(?:product[_\s-]*id|pid)\s*[:=]?\s*(\d+)\b", re.IGNORECASE)

def _session_key(admin_id: int, session_id: str) -> str:
    return f"{admin_id}:{session_id}"

def _get_or_create_session(admin_id: int, session_id: str) -> Dict[str, Any]:
    key = _session_key(admin_id, session_id)
    with _ASM_LOCK:
        s = _ASM_SESSIONS.get(key)
        if not s:
            s = {
                "created_at": time.time(),
                "pending": None,   # "create_order" | "cancel_order" | "confirm_product"
                "data": {},
            }
            _ASM_SESSIONS[key] = s
        return s

def _clear_session(admin_id: int, session_id: str) -> None:
    key = _session_key(admin_id, session_id)
    with _ASM_LOCK:
        _ASM_SESSIONS.pop(key, None)

def _extract_email(text_: str) -> Optional[str]:
    m = _EMAIL_RX.search(text_ or "")
    return m.group(0).strip() if m else None

def _extract_order_id(text_: str) -> Optional[int]:
    m = _ORDER_ID_RX.search(text_ or "")
    return int(m.group(1)) if m else None

def _extract_product_id(text_: str) -> Optional[int]:
    m = _PID_RX.search(text_ or "")
    return int(m.group(1)) if m else None

def _extract_qty(text_: str) -> Optional[int]:
    """
    STRICT qty extraction: only accept explicit qty patterns.
    This prevents digits in emails or model names (S24, 694...) from becoming quantity.
    """
    t = (text_ or "").lower()
    patterns = [
        r"\bqty\s*[:=]?\s*(\d+)\b",
        r"\bquantity\s*[:=]?\s*(\d+)\b",
        r"\bx\s*(\d+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return int(m.group(1))
    return None

def _normalize_name(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()

def _get_product_by_id(db: Session, pid: int) -> Optional[Product]:
    return db.query(Product).filter(Product.id == pid).first()

def _get_product_by_exact_name(db: Session, name: str) -> Optional[Product]:
    """
    STRICT match: normalized case-insensitive equality, not fuzzy ILIKE.
    """
    target = _normalize_name(name)
    if not target:
        return None

    # narrow candidates cheaply then normalize-compare
    like = f"%{name.strip()}%"
    candidates = db.query(Product).filter(Product.name.ilike(like)).all()
    for p in candidates:
        if _normalize_name(p.name) == target:
            return p
    return None

def _suggest_closest_product(db: Session, query: str) -> Optional[Dict[str, Any]]:
    """
    Suggest closest product using vector search (do NOT auto-select).
    Returns {product, dist} or None.
    """
    q = (query or "").strip()
    if not q:
        return None
    try:
        qvec = _vector_literal(_embed_query(q))
        row = db.execute(
            text("""
                SELECT product_id, (embedding <=> CAST(:qvec AS vector)) AS dist
                FROM admin_documents
                WHERE source='product'
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT 1
            """),
            {"qvec": qvec}
        ).mappings().first()
        if not row or not row.get("product_id"):
            return None
        pid = int(row["product_id"])
        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            return None
        return {"product": product, "dist": float(row.get("dist", 1e9))}
    except Exception:
        return None

def _is_yes(text_: str) -> bool:
    t = (text_ or "").strip().lower()
    return t in ("yes", "y", "confirm", "ok", "okay", "proceed", "use it", "use this")

def _is_no(text_: str) -> bool:
    t = (text_ or "").strip().lower()
    return t in ("no", "n", "cancel", "stop", "don't", "dont", "do not")

def _user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()

def _validate_qty(qty: int) -> Optional[str]:
    if qty <= 0:
        return "Quantity must be at least 1."
    if qty > _ASM_MAX_QTY_PER_PRODUCT:
        return f"Quantity exceeds policy limit. Max allowed per product is {_ASM_MAX_QTY_PER_PRODUCT}."
    return None

def _validate_stock(product: Product, qty: int) -> Optional[str]:
    if product.stock <= 0:
        return "Product is out of stock."
    if product.stock < qty:
        return f"Insufficient stock. Available: {product.stock}, requested: {qty}."
    return None

def _create_cod_order_for_user(
    db: Session,
    user: User,
    product: Product,
    qty: int,
    shipping_address: str,
    contact_name: str,
    contact_phone: str,
) -> Order:
    """
    Creates a COD order for the user.
    Leaves status as PENDING_PAYMENT to match current cancel enforcement.
    """
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING_PAYMENT,
        total_amount_cents=product.price_cents * qty,
        payment_method="cod",
        shipping_address=shipping_address,
        contact_name=contact_name,
        contact_email=user.email,
        contact_phone=contact_phone,
    )
    db.add(order)
    db.flush()

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=qty,
        unit_price_cents=product.price_cents
    )
    db.add(item)

    db.commit()
    db.refresh(order)
    return order

async def _ask_llm_to_extract_intent(message: str) -> Dict[str, Any]:
    """
    AI extraction using Groq (via llm_chat). Must return JSON.
    Supported intents: CREATE_ORDER, CANCEL_ORDER, UNKNOWN
    """
    system = (
        "You extract structured data for an admin support workflow. "
        "Return ONLY valid JSON. No markdown, no extra text."
    )
    prompt = f"""
Extract intent and fields from the admin message.

Admin message:
{message}

Return JSON with keys:
intent: "CREATE_ORDER" or "CANCEL_ORDER" or "UNKNOWN"
user_email: string or null
order_id: number or null
product_query: string or null
product_id: number or null
quantity: number or null
shipping_address: string or null
contact_phone: string or null
"""
    data = await llm_chat(prompt=prompt, system=system, temperature=0.0, max_tokens=220)
    txt = (data.get("output") or "").strip()
    try:
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            txt = txt[start:end+1]
        return json.loads(txt)
    except Exception:
        # conservative fallback
        return {
            "intent": "UNKNOWN",
            "user_email": _extract_email(message),
            "order_id": _extract_order_id(message),
            "product_query": None,
            "product_id": _extract_product_id(message),
            "quantity": _extract_qty(message),
            "shipping_address": None,
            "contact_phone": None,
        }

@admin_router.post("/asm/chat", response_model=ASMChatOut)
async def asm_chat(
    body: ASMChatIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin-only ASM chat.
    AI is used to parse intent/fields; server strictly validates and performs DB writes.
    """
    session = _get_or_create_session(current_user.id, body.session_id)
    msg = (body.message or "").strip()

    pending = session.get("pending")
    data = session.get("data", {})

    extracted = await _ask_llm_to_extract_intent(msg)
    intent = (extracted.get("intent") or "").upper()

    # Merge strategy (STRICT):
    # Always overwrite: user_email, order_id, quantity, product_query, product_id when present
    # Fill missing only: shipping_address, contact_phone
    for key in ["user_email", "order_id", "quantity", "product_query", "product_id", "shipping_address", "contact_phone"]:
        val = extracted.get(key)
        if val is None or val == "":
            continue

        if key in ("user_email", "order_id", "quantity", "product_query", "product_id"):
            data[key] = val
        else:
            if not data.get(key):
                data[key] = val

    # Also allow strict parsing from raw message as fallback
    if not data.get("user_email"):
        em = _extract_email(msg)
        if em:
            data["user_email"] = em
    if not data.get("order_id"):
        oid = _extract_order_id(msg)
        if oid is not None:
            data["order_id"] = oid
    if not data.get("product_id"):
        pid = _extract_product_id(msg)
        if pid is not None:
            data["product_id"] = pid
    if not data.get("quantity"):
        qy = _extract_qty(msg)
        if qy is not None:
            data["quantity"] = qy

    # If a new product_query is provided in this message, clear stale resolved product_id/suggestions
    if extracted.get("product_query"):
        data.pop("product_id", None)
        data.pop("suggested_product_id", None)
        data.pop("suggested_product_name", None)

    session["data"] = data

    # Determine pending action when none
    if not pending:
        if intent == "CANCEL_ORDER" or ("cancel" in msg.lower() and "order" in msg.lower()):
            session["pending"] = "cancel_order"
            pending = "cancel_order"
        elif intent == "CREATE_ORDER" or ("create" in msg.lower() and "order" in msg.lower()):
            session["pending"] = "create_order"
            pending = "create_order"
        else:
            return ASMChatOut(reply="I can help with: (1) create order, (2) cancel order.\nExample: 'For user x@y.com cancel order 5' or 'For user x@y.com create order product_id 1 qty 2'.")

    # ---------------------------
    # Pending: confirm suggested product
    # ---------------------------
    if pending == "confirm_product":
        d = session.get("data", {})
        if _is_yes(msg):
            pid = d.get("suggested_product_id")
            if pid:
                d["product_id"] = pid
            d.pop("suggested_product_id", None)
            d.pop("suggested_product_name", None)
            session["data"] = d
            session["pending"] = "create_order"
            return ASMChatOut(reply="Confirmed. Continuing order creation—please provide quantity if not already provided.")
        if _is_no(msg):
            d.pop("suggested_product_id", None)
            d.pop("suggested_product_name", None)
            session["data"] = d
            session["pending"] = "create_order"
            return ASMChatOut(reply="Okay. Please provide the exact product name or product_id.")
        return ASMChatOut(reply="Please reply YES to confirm the suggested product, or NO to provide a different product.")

    # ---------------------------
    # Pending: cancel order (AI-driven)
    # ---------------------------
    if pending == "cancel_order":
        email = data.get("user_email")
        oid = data.get("order_id")

        if not email:
            return ASMChatOut(reply="Please provide the user's email (e.g., 'For user x@y.com cancel order 5').")
        if not oid:
            return ASMChatOut(reply="Please provide the order id to cancel (e.g., 'cancel order 5').")

        user = _user_by_email(db, str(email))
        if not user:
            _clear_session(current_user.id, body.session_id)
            return ASMChatOut(reply=f"Can't find a user with email '{email}'.")

        order = db.query(Order).filter(Order.id == int(oid)).first()
        if not order:
            _clear_session(current_user.id, body.session_id)
            return ASMChatOut(reply=f"Can't find order {oid}.")

        if order.user_id != user.id:
            _clear_session(current_user.id, body.session_id)
            return ASMChatOut(reply=f"Order {order.id} does not belong to user '{user.email}'.")

        if order.status != OrderStatus.PENDING_PAYMENT:
            _clear_session(current_user.id, body.session_id)
            return ASMChatOut(reply=f"Order {order.id} cannot be cancelled at this stage (status={order.status}).")

        order.status = OrderStatus.CANCELLED
        db.commit()

        _clear_session(current_user.id, body.session_id)
        return ASMChatOut(reply=f"Order {order.id} cancelled successfully for user '{user.email}'.")

    # ---------------------------
    # Pending: create order (STRICT product)
    # ---------------------------
    if pending == "create_order":
        email = data.get("user_email")
        if not email:
            return ASMChatOut(reply="Please provide the user's email to create the order.")

        user = _user_by_email(db, str(email))
        if not user:
            _clear_session(current_user.id, body.session_id)
            return ASMChatOut(reply=f"Can't find a user with email '{email}'. Please provide a valid user email.")

        # Product resolution STRICT: product_id OR exact name
        product = None

        pid = data.get("product_id")
        if pid is not None:
            product = _get_product_by_id(db, int(pid))
            if not product:
                data.pop("product_id", None)
                session["data"] = data
                return ASMChatOut(reply=f"Can't find a product with product_id={pid}. Please provide a valid product_id.")

        if not product:
            product_query = data.get("product_query")
            if not product_query:
                return ASMChatOut(reply="Please provide the exact product name, or provide product_id (e.g., product_id 3).")

            product = _get_product_by_exact_name(db, str(product_query))
            if not product:
                suggestion = _suggest_closest_product(db, str(product_query))
                if suggestion and suggestion.get("product"):
                    sugg_p = suggestion["product"]
                    data["suggested_product_id"] = sugg_p.id
                    data["suggested_product_name"] = sugg_p.name
                    session["data"] = data
                    session["pending"] = "confirm_product"
                    return ASMChatOut(
                        reply=(
                            f"I can't find an exact product named '{product_query}'.\n"
                            f"Closest match is '{sugg_p.name}' (product_id={sugg_p.id}).\n"
                            f"Reply YES to use this product, or reply NO and provide the exact product name / product_id."
                        )
                    )
                return ASMChatOut(reply=f"Can't find an exact product named '{product_query}'. Please provide exact name or product_id.")

            data["product_id"] = product.id
            session["data"] = data

        # Ensure product object exists (if coming back from confirmation)
        if not product:
            pid2 = data.get("product_id")
            if pid2:
                product = _get_product_by_id(db, int(pid2))
        if not product:
            return ASMChatOut(reply="Product is not resolved yet. Please provide exact product name or product_id.")

        # Quantity
        qty = data.get("quantity")
        if qty is None:
            return ASMChatOut(reply=f"How many units of '{product.name}' should I order? (Max {_ASM_MAX_QTY_PER_PRODUCT})")

        try:
            qty = int(qty)
        except Exception:
            return ASMChatOut(reply="Quantity must be a number. Please provide a valid quantity (1 or 2).")

        err = _validate_qty(qty)
        if err:
            return ASMChatOut(reply=err)

        err = _validate_stock(product, qty)
        if err:
            return ASMChatOut(reply=err)

        # Missing required fields (use defaults if present)
        shipping_address = data.get("shipping_address") or getattr(user, "default_shipping_address", None)
        contact_phone = data.get("contact_phone") or getattr(user, "default_contact_phone", None)

        missing = []
        if not shipping_address:
            missing.append("shipping address")
        if not contact_phone:
            missing.append("contact phone number")

        if missing:
            need = " and ".join(missing)
            return ASMChatOut(reply=f"I need the user's {need} to create the order. Please provide it.")

        contact_name = getattr(user, "name", None) or "Customer"

        order = _create_cod_order_for_user(
            db=db,
            user=user,
            product=product,
            qty=qty,
            shipping_address=shipping_address,
            contact_name=contact_name,
            contact_phone=contact_phone,
        )

        _clear_session(current_user.id, body.session_id)

        return ASMChatOut(
            reply=(
                f"Order created successfully.\n"
                f"- Order ID: {order.id}\n"
                f"- User: {user.email}\n"
                f"- Payment method: COD\n"
                f"- Status: {order.status}\n"
                f"The COD order is now visible in the user's profile."
            )
        )

    return ASMChatOut(reply="I couldn't process that request. Try: 'For user <email> cancel order <id>' or 'For user <email> create order product_id <id> qty <1|2>'.")

app.include_router(admin_router)

# #warm up the HTTP client on startup; close on shutdown
# @app.on_event("startup")
# async def _startup_llm_client():
#     get_client()  # creates the shared AsyncClient (non-blocking)

@app.on_event("shutdown")
async def _shutdown_llm_client():
    await close_client()

# Request/Response models for /ai/chat
class ChatIn(BaseModel):
    prompt: str = Field(..., min_length=1)
    system: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=4096)

class ChatOut(BaseModel):
    output: str
    provider: str
    model: str

# New endpoints that forward to the LLM service on :8500
@app.get("/ai/health")
async def ai_health():
    return await llm_health()

@app.post("/ai/chat", response_model=ChatOut)
async def ai_chat(body: ChatIn):
    try:
        data = await llm_chat(
            prompt=body.prompt,
            system=body.system,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        return data
    except httpx.HTTPStatusError as e:
        # Forward upstream status & body for easier debugging
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        # Generic upstream failure (network, timeout, etc.)
        raise HTTPException(status_code=502, detail=f"llm upstream error: {e}")

@app.post("/ai/generate-description")
async def generate_description(body: GenerateDescIn):
    specs_text = ""
    if body.specs:
        for k, v in body.specs.items():
            specs_text += f"- {k}: {v}\n"

    prompt = f"""
Create a product description for {body.name} with the following specs:
{specs_text}
Please include the key features and benefits of the product in the description.
Limit the description to. 8-10 lines
"""
    data = await llm_chat(prompt=prompt)
    return {"description": data.get("output")}

# ==========================
# RAG Answer - POST /ai/answer  (Groq-backed, DB-grounded)
# ==========================
class AnswerIn(BaseModel):
    query: str = Field(..., min_length=1)
    k: int = Field(default=12, ge=1, le=50)        # total chunks for initial recall
    products: int = Field(default=5, ge=1, le=20)  # final products to present
    price_band_pct: float = Field(default=0.15, ge=0.05, le=0.5)
    # NEW (H2):
    hybrid: bool = Field(default=True, description="Use hybrid retrieval with RRF")
    rrf_k: int = Field(default=60, ge=1, le=200, description="RRF smoothing constant")
    bm25_k: Optional[int] = Field(default=None, description="Top-k for BM25 (defaults to k)")


class AnswerOut(BaseModel):
    answer: str
    # items: List[dict]

# Numbers that are not glued to letters (so "S24" won't match),
# optional currency sign, with thousands/decimal allowed.
_PRICE_RX = re.compile(
    r"(?<![A-Za-z])\s*(?:₹\s*)?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?![A-Za-z])",
    re.IGNORECASE
)

def _parse_price_band(text: str, pct: float = 0.15, min_rupees: float = 100.0) -> Optional[tuple[int, int]]:
    """
    Extract a target price (in paise) from free text and return a (min,max) band.
    Example: "around 1299.00" -> (lower, upper) for ±pct.
    """
    if not text:
        return None
    clean = text.replace(',', '')
    m = _PRICE_RX.search(clean)
    if not m:
        return None
    try:
        rupees = float(m.group(1))
        if rupees < min_rupees:
            # Too small to be a price in this catalog; treat as "no price"
            return None
        paise = int(round(rupees * 100))
        lower = max(0, int(floor(paise * (1 - pct))))
        upper = int(ceil(paise * (1 + pct)))
        return (lower, upper)
    except Exception:
        return None

def _group_best_by_product(rows):
    """
    Given rows with product_id, title, content, metadata, dist/score,
    keep only the best row per product_id (lowest distance / highest score).
    """
    best = {}
    for r in rows:
        pid = r.get("product_id")
        if pid is None:
            continue
        prev = best.get(pid)
        if prev is None:
            best[pid] = r
        else:
            # smaller dist is better
            if float(r.get("dist", 1e9)) < float(prev.get("dist", 1e9)):
                best[pid] = r
    return list(best.values())

def _format_context(products: List[dict], max_chars_per: int = 500) -> str:
    """
    Build a compact, readable context that includes product facts.
    """
    lines = []
    for i, r in enumerate(products, start=1):
        meta = r.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        price_cents = meta.get("price_cents")
        price_str = f"₹{(price_cents or 0)/100:.2f}" if price_cents is not None else "N/A"
        title = (r.get("title") or "").strip() or "(untitled)"
        snippet = (r.get("content") or "")
        if len(snippet) > max_chars_per:
            snippet = snippet[:max_chars_per] + "…"

        lines.append(
            f"PRODUCT {i}\n"
            f"id: {r.get('product_id')}\n"
            f"name: {title}\n"
            f"price: {price_str}\n"
            f"snippet: {snippet}\n"
        )
    return "\n".join(lines) if lines else "(no products)"


_POLICY_KEYWORDS = (
    "policy", "cancel", "cancellation", "return", "refund", "exchange",
    "cod", "cash on delivery", "replacement", "warranty"
)

def _looks_like_policy_query(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in _POLICY_KEYWORDS)

def _looks_like_order_query(q: str) -> bool:
    ql = (q or "").lower()
    # common patterns: "order", "order 5", "order #5"
    return ("order" in ql) or ("orders" in ql)

def _format_policy_context(rows: List[dict], max_chars_per: int = 700) -> str:
    """
    Convert retrieved policy chunks to a compact context string.
    """
    lines = []
    for i, r in enumerate(rows, start=1):
        title = (r.get("title") or "").strip() or f"Policy chunk {i}"
        content = (r.get("content") or "").strip()
        if len(content) > max_chars_per:
            content = content[:max_chars_per] + "…"
        lines.append(f"POLICY {i}\nTitle: {title}\n{content}\n")
    return "\n".join(lines) if lines else "(no policy context)"

@app.post("/ai/answer", response_model=AnswerOut)
async def ai_answer(body: AnswerIn, db: Session = Depends(get_db)):
    """
    Policy-aware RAG answer grounded in DB:
    - Retrieves product docs (always)
    - Retrieves policy docs when query looks policy-related
    - Retrieves order docs when query mentions orders
    - Uses hybrid retrieval (vector + BM25 via RRF) when body.hybrid=True
    - Calls Groq via llm_client.chat and returns only {"answer": "..."}
    """
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    include_policy = _looks_like_policy_query(q)
    include_orders = _looks_like_order_query(q)

    # Price band applies only to product retrieval
    band = _parse_price_band(q, pct=body.price_band_pct)  # (min,max) in paise or None

    # Embed query once
    qvec = _vector_literal(_embed_query(q))

    # ----------------------------
    # Source-aware retrieval (vector + optional BM25 -> RRF)
    # ----------------------------
    def _vector_rows_for_source(source: str, topk: int, band_opt: Optional[tuple[int, int]] = None):
        # Product can be band-filtered; other sources should ignore band
        if source == "product" and band_opt:
            sql = """
                SELECT id, source, product_id, title, content, metadata,
                       (embedding <=> CAST(:qvec AS vector)) AS dist
                FROM admin_documents
                WHERE source='product'
                  AND (metadata ? 'price_cents')
                  AND ((metadata->>'price_cents') ~ '^[0-9]+$')
                  AND ((metadata->>'price_cents')::int BETWEEN :minp AND :maxp)
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :k
            """
            return db.execute(
                text(sql),
                {"qvec": qvec, "k": topk, "minp": band_opt[0], "maxp": band_opt[1]},
            ).mappings().all()

        sql = """
            SELECT id, source, product_id, title, content, metadata,
                   (embedding <=> CAST(:qvec AS vector)) AS dist
            FROM admin_documents
            WHERE source = :src
            ORDER BY embedding <=> CAST(:qvec AS vector) ASC
            LIMIT :k
        """
        return db.execute(text(sql), {"qvec": qvec, "k": topk, "src": source}).mappings().all()

    def _bm25_rows_for_source(source: str, topk: int, band_opt: Optional[tuple[int, int]] = None):
        # BM25 retrieval via tsvector; band filter only when source='product'
        if source == "product" and band_opt:
            sql = """
                WITH q AS (SELECT websearch_to_tsquery('english', :q) AS tsq)
                SELECT d.id, d.source, d.product_id, d.title, d.content, d.metadata,
                       ts_rank_cd(d.tsv, q.tsq) AS bm25
                FROM admin_documents d, q
                WHERE d.source='product'
                  AND d.tsv @@ q.tsq
                  AND (d.metadata ? 'price_cents')
                  AND ((d.metadata->>'price_cents') ~ '^[0-9]+$')
                  AND ((d.metadata->>'price_cents')::int BETWEEN :minp AND :maxp)
                ORDER BY bm25 DESC
                LIMIT :k
            """
            return db.execute(
                text(sql),
                {"q": q, "k": topk, "minp": band_opt[0], "maxp": band_opt[1]},
            ).mappings().all()

        sql = """
            WITH q AS (SELECT websearch_to_tsquery('english', :q) AS tsq)
            SELECT d.id, d.source, d.product_id, d.title, d.content, d.metadata,
                   ts_rank_cd(d.tsv, q.tsq) AS bm25
            FROM admin_documents d, q
            WHERE d.source = :src
              AND d.tsv @@ q.tsq
            ORDER BY bm25 DESC
            LIMIT :k
        """
        return db.execute(text(sql), {"q": q, "k": topk, "src": source}).mappings().all()

    def _retrieve_source(source: str, topk: int, band_opt: Optional[tuple[int, int]] = None):
        vec_rows = _vector_rows_for_source(source, topk, band_opt)

        if not body.hybrid:
            return vec_rows

        bm_k = body.bm25_k or topk
        bm_rows = _bm25_rows_for_source(source, bm_k, band_opt)
        return _rrf_fuse(vec_rows, bm_rows, rrf_k=body.rrf_k)

    # ----------------------------
    # 1) Retrieve products (always) with progressive fallback if band is too tight
    # ----------------------------
    prod_rows = _retrieve_source("product", body.k, band)

    if not prod_rows and band:
        widen = (max(0, int(band[0] * 0.9)), int(band[1] * 1.1))
        prod_rows = _retrieve_source("product", body.k, widen)

    if not prod_rows:
        prod_rows = _retrieve_source("product", body.k, None)

    per_product = _group_best_by_product(prod_rows)[: body.products]

    # ----------------------------
    # 2) Retrieve policy chunks (conditional)
    # ----------------------------
    policy_rows: List[dict] = []
    if include_policy:
        # Pull a few policy chunks; no price band for policies
        policy_rows = _retrieve_source("policy", topk=min(8, body.k), band_opt=None)[:5]

    # ----------------------------
    # 3) Retrieve order summaries (conditional)
    # ----------------------------
    order_rows: List[dict] = []
    if include_orders:
        order_rows = _retrieve_source("order", topk=min(8, body.k), band_opt=None)[:5]

    # If nothing found at all
    if not per_product and not policy_rows and not order_rows:
        return AnswerOut(answer="I couldn't find relevant information in the current data. Please try a different query.")

    # ----------------------------
    # Build combined CONTEXT for the model
    # ----------------------------
    parts: List[str] = []

    if per_product:
        parts.append("PRODUCT CONTEXT\n--------------\n" + _format_context(per_product))

    if order_rows:
        # reuse existing policy formatter for orders, but label it as ORDER
        order_ctx = _format_policy_context(order_rows, max_chars_per=700).replace("POLICY", "ORDER")
        parts.append("ORDER CONTEXT\n------------\n" + order_ctx)

    if policy_rows:
        parts.append("POLICY CONTEXT\n-------------\n" + _format_policy_context(policy_rows, max_chars_per=700))

    context = "\n\n".join(parts)

    # ----------------------------
    # Prompt Groq (answer only from context)
    # ----------------------------
    system = (
        "You are a support assistant for an e-commerce app. "
        "Answer ONLY using the CONTEXT provided. "
        "If the answer is not in the context, say you don't know. "
        "If a policy section says CURRENT vs PLANNED, keep that meaning and do not claim PLANNED rules are enforced. "
        "Do not invent rules, product details, or order statuses."
    )

    prompt = f"""
CONTEXT
-------
{context}

USER QUERY
----------
{q}

INSTRUCTIONS
------------
- Use ONLY the CONTEXT.
- If the question is about cancel/return/refund/exchange/policy, rely on POLICY CONTEXT.
- If a rule is marked PLANNED, clearly say it is planned and not currently enforced.
- Keep the answer concise and actionable.
"""

    try:
        data = await llm_chat(prompt=prompt, system=system, temperature=0.2, max_tokens=450)
        answer_text = data.get("output", "").strip()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"llm upstream error: {e}")

    return AnswerOut(answer=answer_text)

    # 6) Try to extract PRODUCTS JSON array if present
    # items: List[dict] = []
    # try:
    #     for line in answer_text.splitlines():
    #         if line.strip().startswith("PRODUCTS:"):
    #             json_part = line.split("PRODUCTS:", 1)[-1].strip()
    #             try:
    #                 items = json.loads(json_part)
    #             except Exception:
    #                 items = ast.literal_eval(json_part)
    #             break
    # except Exception:
    #     items = []

    # # Fallback: map retrieved rows if model didn't return structured items
    # if not items:
    #     for r in per_product:
    #         meta = r.get("metadata") or {}
    #         if isinstance(meta, str):
    #             try:
    #                 meta = json.loads(meta)
    #             except Exception:
    #                 meta = {}
    #         items.append({
    #             "product_id": r.get("product_id"),
    #             "title": r.get("title"),
    #             "price_cents": meta.get("price_cents"),
    #             "score": round(1.0 - float(r.get("dist", 0.0)), 4)
    #         })

    # return AnswerOut(answer=answer_text, items=items)


@app.put("/me/address", response_model=UserOut)
def save_address(
    payload: AddressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ):
    current_user.default_shipping_address = payload.default_shipping_address
    current_user.default_contact_phone = payload.default_contact_phone
    db.commit()
    db.refresh(current_user)
    return current_user
