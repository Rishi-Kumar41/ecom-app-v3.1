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
from schemas import UserCreate, UserOut, TokenOut, ProductOut, OrderCreate, OrderOut, AdminProductCreate
from auth import hash_password, verify_password, create_access_token, get_current_user
from seed import seed_products
from permission import require_roles
from schemas import GenerateDescIn

# ---------- NEW imports for RAG/embeddings & parsing ----------
from functools import lru_cache
try:
    from sentence_transformers import SentenceTransformer
except Exception:
    SentenceTransformer = None

import re
from math import floor, ceil
import ast
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
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Stripe minimum amount check (50 cents USD ~ 50 INR in test mode)
    MIN_AMOUNT_CENTS = 5000  # 50 INR in paise
    if order.total_amount_cents < MIN_AMOUNT_CENTS:
        print(f"Warning: Order total {order.total_amount_cents} paise is below Stripe minimum. Adjusting to {MIN_AMOUNT_CENTS}.")
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

# admin search (Support UI will call this)
@admin_router.get("/search")
def admin_search(
    q: Optional[str] = Query(None, description="Query text. Empty returns recent items."),
    k: int = Query(10, ge=1, le=50, description="Number of results."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Vector search over admin_documents using pgvector + cosine distance.

    - If `q` is empty -> returns most recently updated chunks (useful for smoke tests).
    - Else -> embed `q` with BGE-M3 and order by cosine distance (embedding <=> :qvec).
    """
    if not q or not q.strip():
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
    else:
        qvec = _vector_literal(_embed_query(q.strip()))
        rows = db.execute(
            text("""
                SELECT id, source, product_id, title, content, metadata,
                       (1.0 - (embedding <=> CAST(:qvec AS vector))) AS score
                FROM admin_documents
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :k
            """),
            {"qvec": qvec, "k": k}
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

class AnswerOut(BaseModel):
    answer: str
    items: List[dict]

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

@app.post("/ai/answer", response_model=AnswerOut)
async def ai_answer(body: AnswerIn, db: Session = Depends(get_db)):
    """
    RAG answer grounded in DB:
    - parse price (optional) -> band
    - retrieve top-k chunks (vector + optional price filter)
    - group best per product
    - call your Groq-backed chat with strict instructions to answer ONLY from context
    """
    q = (body.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # 1) Optional numeric constraint
    band = _parse_price_band(q, pct=body.price_band_pct)  # (min,max) in paise or None

    # 2) Embed the query and retrieve from admin_documents
    qvec = _vector_literal(_embed_query(q))
# 3) Retrieval with progressive fallback
    def _retrieve(db: Session, qvec: str, k: int, band: Optional[tuple[int, int]]):
        if band:
            # Price-constrained retrieval (only if price exists and seems plausible)
            sql = """
                SELECT product_id, title, content, metadata,
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
                {"qvec": qvec, "k": k, "minp": band[0], "maxp": band[1]}
            ).mappings().all()
        else:
            # Pure vector (no numeric filter)
            sql = """
                SELECT product_id, title, content, metadata,
                       (embedding <=> CAST(:qvec AS vector)) AS dist
                FROM admin_documents
                WHERE source='product'
                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                LIMIT :k
            """
            return db.execute(text(sql), {"qvec": qvec, "k": k}).mappings().all()

    raw = _retrieve(db, qvec, body.k, band)

    if not raw and band:
        # widen band once (e.g., -10% / +10% around original band edges)
        widen = (max(0, int(band[0] * 0.9)), int(band[1] * 1.1))
        raw = _retrieve(db, qvec, body.k, widen)

    if not raw:
        # final fallback: no band at all
        raw = _retrieve(db, qvec, body.k, None)
    # 3) Group best by product (avoid multiple chunks of same product)
    per_product = _group_best_by_product(raw)
    per_product = per_product[: body.products]

    if not per_product:
        return AnswerOut(
            answer="I couldn't find matching products right now. Try broadening the query or another term.",
            items=[]
        )

    # 4) Build a compact CONTEXT from the selected products
    context = _format_context(per_product)

    # 5) Prompt Groq via your existing llm_client.chat
    system = (
        "You are a retail assistant. Answer ONLY using the CONTEXT. "
        "If context is insufficient, say you don't know. "
        "Return concise, accurate suggestions."
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
- Use ONLY the CONTEXT facts (ids, names, prices) to answer the user.
- If price constraints are implied, respect them.
- Prefer 3-5 items if available.
- Provide a short, helpful answer first.
- Then output a JSON array named PRODUCTS, where each element is:
  {{"product_id": number, "name": string, "price_cents": number}}

FORMAT
------
Write a brief answer paragraph, then newline, then:
PRODUCTS: <json array here>
"""
    try:
        data = await llm_chat(prompt=prompt, system=system, temperature=0.2, max_tokens=400)
        answer_text = data.get("output", "").strip()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"llm upstream error: {e}")

    # 6) Try to extract PRODUCTS JSON array if present
    items: List[dict] = []
    try:
        for line in answer_text.splitlines():
            if line.strip().startswith("PRODUCTS:"):
                json_part = line.split("PRODUCTS:", 1)[-1].strip()
                try:
                    items = json.loads(json_part)
                except Exception:
                    items = ast.literal_eval(json_part)
                break
    except Exception:
        items = []

    # Fallback: map retrieved rows if model didn't return structured items
    if not items:
        for r in per_product:
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            items.append({
                "product_id": r.get("product_id"),
                "title": r.get("title"),
                "price_cents": meta.get("price_cents"),
                "score": round(1.0 - float(r.get("dist", 0.0)), 4)
            })

    return AnswerOut(answer=answer_text, items=items)