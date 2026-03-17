
import os
from typing import Optional, Dict, Any
import httpx

# Base URL of your LLM service (dev default points at :8500)
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://localhost:8500/api").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY")  # optional: for future server-to-server auth

_client: Optional[httpx.AsyncClient] = None

def get_client() -> httpx.AsyncClient:
    """Return a singleton AsyncClient configured for the LLM service."""
    global _client
    if _client is None:
        headers = {}
        if LLM_API_KEY:
            headers["x-api-key"] = LLM_API_KEY
        _client = httpx.AsyncClient(
            base_url=LLM_API_BASE,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
    return _client

async def close_client() -> None:
    """Close and reset the shared client (called on app shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None

# ---------- Upstream calls ----------

async def health() -> Dict[str, Any]:
    """GET /api/health → {status, provider, model}"""
    c = get_client()
    r = await c.get("/health")
    r.raise_for_status()
    return r.json()

async def chat(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> Dict[str, Any]:
    """
    POST /api/chat → {output, provider, model}
    Mirrors your LLM service schema.
    """
    payload = {
        "prompt": prompt,
        "system": system,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    c = get_client()
    r = await c.post("/chat", json=payload)
    r.raise_for_status()
    return r.json()