ECOM-APP-V3.1

A full‑stack demo e‑commerce app:
- Backend: FastAPI + SQLAlchemy + SQLite (auto-seeded products)
- Frontend: Angular 19 (standalone), served via Angular CLI dev server

This README covers: setup, run, API docs (Swagger), local assets, the “saved address” profile feature, checkout prefill/validation, and troubleshooting.

---

PROJECT LAYOUT

 ecom-app-v3.1/
 ├─ server/                  # FastAPI backend
 │  ├─ main.py               # app entry
 │  ├─ models.py             # SQLAlchemy models
 │  ├─ schemas.py            # Pydantic schemas
 │  ├─ database.py           # engine/session
 │  ├─ seed.py               # product seed data
 │  └─ ecom.db               # SQLite DB (created at first run)
 └─ client/                  # Angular 19 frontend
    ├─ src/
    │  ├─ assets/products/   # local images used by products
    │  ├─ environments/environment.ts
    │  └─ pages/…            # UI pages (profile, checkout, orders, etc.)
    └─ angular.json

---

PREREQUISITES

- Python 3.9+ (3.11 recommended)
- Node.js LTS compatible with Angular 19 (e.g., 20.11+ or 22+)
- npm 9+ (ships with Node LTS)
- macOS paths are used below; adjust for other OSes

Tip: If you use nvm, run: nvm use 20 (or 22) when working in client/.

---

1) BACKEND — FASTAPI

Create & activate venv, install deps
```bash
  cd /Users/rikumar/Documents/ecom-app-v3.1/server
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
```
The app uses SQLite with a file named ecom.db in server/. It is created automatically on first run (and products are auto‑seeded).

CORS (dev)

We allow http://localhost:4200 and http://127.0.0.1:4200 (Angular dev) to call http://127.0.0.1:8000 (API):

  # main.py (already present)
  from fastapi.middleware.cors import CORSMiddleware

  app.add_middleware(
      CORSMiddleware,
      allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
      allow_credentials=True,
      allow_methods=["*"],
      allow_headers=["*"],
  )

Run API

  uvicorn main:app --reload --port 8000

Swagger (interactive API docs)

- Open http://127.0.0.1:8000/docs
- Authorize (top‑right) using username = your email and password = your password
  (OAuth2 “password” flow — Swagger calls /auth/login on your behalf)
- Try protected endpoints (e.g., GET /me, PUT /me/address)

---

2) DATABASE & SEED DATA

- Database file: /Users/rikumar/Documents/ecom-app-v3.1/server/ecom.db
- CLI quick look:
    cd /Users/rikumar/Documents/ecom-app-v3.1/server
    sqlite3 ecom.db ".tables"
    sqlite3 ecom.db "SELECT id, name, price_cents FROM products LIMIT 5;"
- Reseed (dev‑only): delete the DB and restart the API:
    rm -f ecom.db
    uvicorn main:app --reload --port 8000

---

3) FRONTEND — ANGULAR 19

Install & run

  cd /Users/rikumar/Documents/ecom-app-v3.1/client
  # ensure Node 20 or 22: nvm use 20
  rm -rf node_modules package-lock.json
  npm install
  npm start

- App opens at http://localhost:4200
- API base is configured in src/environments/environment.ts:
    export const environment = { production: false, apiBase: 'http://127.0.0.1:8000' };

Polyfills & source maps (dev)

- angular.json is set with "polyfills": ["zone.js"]
- Dev source maps are enabled so you can see .ts in DevTools → Sources.
  If you don’t see them:
  - Chrome DevTools → Settings → Enable JavaScript source maps
  - Ensure build.options.sourceMap: true and serve.defaultConfiguration: "development"
  - Hard refresh (Cmd+Shift+R)

---

4) LOCAL PRODUCT IMAGES (ASSETS)

The seed data uses local assets at /assets/products/.... Make sure the folder exists:
  client/src/assets/products/

If you need placeholder images, drop JPGs into this folder with names referenced in seed.py (e.g., s24.jpg, t7-1tb.jpg, …). A ready‑made assets zip was provided earlier—extract to client/src/assets/.

---

5) FEATURES IMPLEMENTED

5.1 Saved address (Profile) → Prefill (Checkout)

- Backend changes:
  - users table: new nullable columns
      default_shipping_address: TEXT
      default_contact_phone: VARCHAR(30)
  - UserOut schema now includes these fields
  - PUT /me/address to save/update them
  - GET /me returns them

- Profile page (/profile):
  - “Saved shipping address” textarea + phone input
  - Save calls PUT /me/address and persists in local storage
  - On load, page pre‑populates from /me

- Checkout page (/checkout):
  - Required fields: contact name, email, mobile, shipping address
  - Prefill: name, email (from user) + address & phone (from saved profile)
  - Can edit before placing an order

5.2 Orders & Order Details (polish)

- Orders list:
  - Color‑coded status badge (PAID, PENDING_PAYMENT, CANCELLED)
  - Ship‑to (shortened), contact summary
  - Copy Order ID button (brief “Copied!”)
  - “View” & “Cancel” actions

- Order Details:
  - Header with Order #, Copy ID, and status badge
  - Full “Ship to” and “Contact” blocks
  - Items + total, simple tracking

Badge colors are in src/styles.css:
  .badge--ok{background:#dcfce7;color:#166534;border-color:#86efac}
  .badge--warn{background:#fef9c3;color:#854d0e;border-color:#fde68a}
  .badge--err{background:#fee2e2;color:#991b1b;border-color:#fecaca}

---

6) QUICK START (HAPPY PATH)

1. Start API: uvicorn main:app --reload --port 8000
2. Start UI: npm start (in client/)
3. Register → Login
4. Profile → Save “Saved shipping address” (and phone)
5. Products → Add to cart → Checkout
6. Confirm prefilled fields → Place Order
7. Payment → “Pay with Dummy Gateway”
8. Orders / Order Details

---

7) CLI SMOKE TESTS (OPTIONAL)

# 0) Products
curl -s http://127.0.0.1:8000/products | head
token
# 1) Register (adjust email as needed)
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Rishi","email":"rishi.test@example.com","password":"secret123"}'

# 2) Login (capture token)
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=rishi.test@example.com&password=secret123" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
echo "TOKEN=$TOKEN"

# 3) Save default address
curl -s -X PUT http://127.0.0.1:8000/me/address \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"default_shipping_address":"Door #12, 2nd Main, Indiranagar, Bangalore 560038", "default_contact_phone":"+91-90000-00000"}'

# 4) Create order for product id 1
curl -s -X POST http://127.0.0.1:8000/orders \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"items":[{"product_id":1,"quantity":1}], "payment_method":"dummy",
       "shipping_address":"Door #12, 2nd Main, Indiranagar, Bangalore 560038",
       "contact_name":"Rishi","contact_email":"rishi.test@example.com","contact_phone":"+91-90000-00000"}'

---

8) TROUBLESHOOTING

CORS error in browser
- Ensure API middleware allows http://localhost:4200 and http://127.0.0.1:4200
- Restart Uvicorn; hard refresh browser (Cmd+Shift+R)
- If only preflight (OPTIONS) succeeds and the actual request fails: check server logs for a 500 — browsers often show a “CORS” message when the server threw an exception and didn’t attach headers

Password hashing / registration 500
- Classic bcrypt accepts passwords up to 72 bytes.
  Use normal-length passwords in dev, or (optional) pin bcrypt to a stable version in your venv:
    pip install "bcrypt==4.3.0"
- Alternative (optional): switch Passlib to bcrypt_sha256 to safely accept longer passwords.

Images 404
- We now use local assets. Ensure client/src/assets/products/ contains the images referenced in seed.py.

DevTools doesn’t show TypeScript
- Chrome DevTools → Enable JavaScript source maps
- client/angular.json → build.options.sourceMap: true, serve.defaultConfiguration: "development"
- Hard refresh

Environment check
- UI: Node 20.11+ / 22+
- API: ensure you’re running the intended virtualenv (source .venv/bin/activate)

---

9) NOTES & MAINTENANCE

- Reseeding: deleting ecom.db will wipe users/orders (demo only) and reseed products.
- Saved address is stored per user (single default). Extensible to an Address Book later.
- Zones/Polyfills: app runs with Zone.js (polyfills: ["zone.js"]). Zoneless is possible later, but current structure remains unchanged.

---

License: For internal demo and training use.
