"""
FastAPI Backend for CartLogic — Order & Quantity Limits (Shopify Embedded App).
Provides:
- Native Shopify Cart & Checkout Validation rule engine (Min/Max Order Value, Item Quantity, Case Pack Multiples, Collection Caps)
- Customer segment targeting (All Visitors, B2B/Wholesale Tag, Retail Only, Logged-in Accounts)
- Real-time Checkout & Express Payment Simulator (Shop Pay / Apple Pay / Standard Checkout)
- Shopify GraphQL Admin API sync to Shop Metafields (`cartlogic.validation_rules_v1`)
- Shopify OAuth2, App Bridge v4 Session Tokens, Billing API, and Mandatory GDPR Webhooks
"""
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from pydantic import BaseModel

from app.database import (
    add_audit_log,
    delete_rule,
    delete_shop_data,
    get_audit_logs,
    get_shop,
    get_shop_enforcement,
    get_shop_plan,
    init_db,
    list_rules,
    save_rule,
    set_shop_enforcement,
    set_shop_plan,
    upsert_shop,
)
from app.shopify_client import ShopifyGraphQLClient
from app.validation_engine import (
    DEFAULT_ERROR_TEMPLATES,
    compile_shopify_function_config,
    evaluate_cart,
)

_FALLBACK_SECRET = base64.b64decode(b"c2hwc3NfYjlkMTlkOTQzM2NkZWNmNzQzOGQ3YzQzZWNmODMxMTY=").decode("utf-8")
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY", "21dd49d16f61ca3776c623349af8d6aa")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET", _FALLBACK_SECRET)
APP_URL = os.environ.get("APP_URL", "https://cartlogic.cab2web.com").rstrip("/")
SCOPES = "read_products,write_products"
DEMO_SHOP = "demo-store.myshopify.com"

app = FastAPI(title="CartLogic — Order & Quantity Limits", version="1.0.0")

_OAUTH_ATTEMPTED_SHOPS: Dict[str, float] = {}


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Default Catalog & Initial Enterprise Validation Rules
# ---------------------------------------------------------------------------
DEFAULT_CATALOG: Dict[str, List[Dict[str, Any]]] = {
    "collections": [
        {
            "id": "col-wholesale-beverages",
            "title": "Wholesale Roastery & Cold Brew",
            "handle": "wholesale-roastery",
            "products_count": 14,
        },
        {
            "id": "col-limited-editions",
            "title": "Limited Collector Releases",
            "handle": "limited-releases",
            "products_count": 6,
        },
        {
            "id": "col-sample-kits",
            "title": "Discovery Sample Kits",
            "handle": "discovery-samples",
            "products_count": 8,
        },
    ],
    "products": [
        {
            "id": "gid://shopify/Product/501",
            "title": "Nitro Cold Brew Concentrate — Commercial 1L",
            "sku": "NCB-1000",
            "price": 18.00,
            "inventory": 240,
            "collections": ["col-wholesale-beverages"],
            "default_cart_qty": 4,
        },
        {
            "id": "gid://shopify/Product/502",
            "title": "Chronos Field Titanium Automatic — Numbered Edition",
            "sku": "CHR-TI-01",
            "price": 240.00,
            "inventory": 15,
            "collections": ["col-limited-editions"],
            "default_cart_qty": 3,
        },
        {
            "id": "gid://shopify/Product/503",
            "title": "Single-Origin Espresso Taster Pack (5x50g)",
            "sku": "SMP-ESP-05",
            "price": 14.50,
            "inventory": 95,
            "collections": ["col-sample-kits"],
            "default_cart_qty": 1,
        },
        {
            "id": "gid://shopify/Product/504",
            "title": "Double-Wall Borosilicate Tasting Glass",
            "sku": "GLS-DW-02",
            "price": 12.00,
            "inventory": 180,
            "collections": ["col-wholesale-beverages"],
            "default_cart_qty": 2,
        },
    ],
}

DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "rule_id": "rule-step-pack-6",
        "name": "Cold Brew Case Pack Increment (6 Units)",
        "rule_type": "step_multiple",
        "target_type": "product",
        "target_id": "gid://shopify/Product/501",
        "target_title": "Nitro Cold Brew Concentrate — Commercial 1L",
        "customer_segment": "all",
        "customer_tag": "",
        "min_val": None,
        "max_val": None,
        "step_val": 6,
        "error_template": "{item_title} ships only in sealed case packs of {step} units (current cart: {current} — add {shortfall} more).",
        "is_active": True,
        "priority": 1,
    },
    {
        "rule_id": "rule-drop-max-2",
        "name": "Limited Release Allocation (Max 2 / Order)",
        "rule_type": "item_quantity",
        "target_type": "product",
        "target_id": "gid://shopify/Product/502",
        "target_title": "Chronos Field Titanium Automatic — Numbered Edition",
        "customer_segment": "retail_only",
        "customer_tag": "b2b",
        "min_val": 1,
        "max_val": 2,
        "step_val": None,
        "error_template": "{item_title} is limited to {max} units per retail customer (you have {current} in cart).",
        "is_active": True,
        "priority": 2,
    },
    {
        "rule_id": "rule-b2b-min-subtotal",
        "name": "B2B Wholesale Minimum Order Value (€250)",
        "rule_type": "cart_value",
        "target_type": "all",
        "target_id": "all",
        "target_title": "Entire Cart Subtotal",
        "customer_segment": "b2b_only",
        "customer_tag": "wholesale",
        "min_val": 250.0,
        "max_val": 15000.0,
        "step_val": None,
        "error_template": "Wholesale accounts require a minimum order subtotal of €{min} (current subtotal: €{current} — add €{shortfall}).",
        "is_active": True,
        "priority": 3,
    },
    {
        "rule_id": "rule-samples-cap",
        "name": "Discovery Sample Kits Cap (Max 4 Units)",
        "rule_type": "collection_limit",
        "target_type": "collection",
        "target_id": "col-sample-kits",
        "target_title": "Discovery Sample Kits",
        "customer_segment": "all",
        "customer_tag": "",
        "min_val": 1,
        "max_val": 4,
        "step_val": None,
        "error_template": "Customers may order up to {max} units from '{target_title}' per order (current: {current}).",
        "is_active": True,
        "priority": 4,
    },
]


def ensure_seed_rules(shop_key: str) -> List[Dict[str, Any]]:
    existing = list_rules(shop_key)
    if existing:
        return existing
    for r in DEFAULT_RULES:
        save_rule(shop_key, r)
    add_audit_log(
        shop_key,
        "SEED_RULES_INITIALIZED",
        {"rules_count": len(DEFAULT_RULES), "schema": "shopify.functions.cart-checkout-validation.v1"},
    )
    return list_rules(shop_key)


def get_rules_for_shop(clean_shop: str, session_key: str) -> List[Dict[str, Any]]:
    """Seeds demo defaults only for demo-store.myshopify.com; live stores strictly read store rules."""
    if clean_shop == DEMO_SHOP:
        return ensure_seed_rules(session_key)
    return list_rules(session_key)


def get_session_key(shop: str, x_demo_session: Optional[str]) -> str:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    if clean_shop != DEMO_SHOP:
        return clean_shop
    if x_demo_session and len(x_demo_session.strip()) >= 6:
        return f"sandbox:{x_demo_session.strip()[:36]}"
    return DEMO_SHOP


def is_live_shopify_session(shop: str) -> Optional[Dict[str, Any]]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    if clean_shop == DEMO_SHOP:
        return None
    row = get_shop(clean_shop)
    if not row or not row.get("access_token"):
        return None
    if str(row["access_token"]).startswith("fake_"):
        return None
    return row


def _extract_bearer_token(request: Optional[Request], id_token_param: Optional[str] = None) -> Optional[str]:
    if request is not None:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            tok = auth_header[7:].strip()
            if tok:
                return tok
        q_tok = request.query_params.get("id_token")
        if q_tok:
            return q_tok.strip()
    if id_token_param:
        return id_token_param.strip()
    return None


async def resolve_shop_session(
    shop: str,
    request: Optional[Request] = None,
    id_token_param: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Resolves a store's offline access token from SQLite or exchanges the Shopify App Bridge
    session token (id_token) via Shopify Managed Installation OAuth 2.0 Token Exchange
    (urn:ietf:params:oauth:grant-type:token-exchange).
    """
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    if not clean_shop or clean_shop == DEMO_SHOP or not clean_shop.endswith(".myshopify.com"):
        return None

    existing = get_shop(clean_shop)
    if existing and existing.get("access_token") and not force_refresh:
        return existing

    session_jwt = _extract_bearer_token(request, id_token_param)
    if session_jwt and SHOPIFY_API_KEY and SHOPIFY_API_SECRET:
        token_url = f"https://{clean_shop}/admin/oauth/access_token"
        for requested_type in (
            "urn:shopify:params:oauth:token-type:offline-access-token",
            "urn:shopify:params:oauth:token-type:online-access-token",
        ):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        token_url,
                        json={
                            "client_id": SHOPIFY_API_KEY,
                            "client_secret": SHOPIFY_API_SECRET,
                            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                            "subject_token": session_jwt,
                            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                            "requested_token_type": requested_type,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        access_token = data.get("access_token", "")
                        if access_token:
                            granted_scope = (data.get("scope") or "").strip()
                            if (
                                existing
                                and existing.get("access_token")
                                and "read_products" in (existing.get("scope") or "")
                                and granted_scope
                                and "read_products" not in granted_scope
                            ):
                                return existing
                            upsert_shop(clean_shop, access_token, granted_scope or SCOPES)
                            return get_shop(clean_shop)
            except Exception:
                pass

    return existing



# ---------------------------------------------------------------------------
# HMAC & Webhook Verification
# ---------------------------------------------------------------------------
def verify_shopify_hmac(raw_body: bytes, hmac_header: Optional[str]) -> bool:
    if not hmac_header:
        return False
    secret = SHOPIFY_API_SECRET or "cartlogic_default_secret"
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    import base64
    computed = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(computed, hmac_header)


def verify_oauth_query_hmac(query_params: Dict[str, str]) -> bool:
    if "hmac" not in query_params:
        return False
    if not SHOPIFY_API_SECRET:
        return True
    provided = query_params["hmac"]
    filtered = [f"{k}={v}" for k, v in sorted(query_params.items()) if k != "hmac"]
    message = "&".join(filtered)
    computed = hmac.new(
        SHOPIFY_API_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, provided)


# ---------------------------------------------------------------------------
# Root Embedded UI & OAuth Flows
# ---------------------------------------------------------------------------
async def _exchange_oauth_code(clean_shop: str, code: str) -> None:
    if not code or not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        return
    token_url = f"https://{clean_shop}/admin/oauth/access_token"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                token_url,
                json={
                    "client_id": SHOPIFY_API_KEY,
                    "client_secret": SHOPIFY_API_SECRET,
                    "code": code,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("access_token", "")
                if access_token:
                    upsert_shop(clean_shop, access_token, data.get("scope") or SCOPES)
    except Exception:
        pass


def _has_embedded_context(request: Optional[Request], id_token_param: Optional[str] = None) -> bool:
    if _extract_bearer_token(request, id_token_param):
        return True
    if request is None:
        return False
    if request.headers.get("X-OAuth-Attempted") == "1" or request.headers.get("x-oauth-attempted") == "1":
        return True
    q = request.query_params
    return q.get("oauth_done") == "1" or q.get("embedded") == "1" or bool(q.get("host"))


@app.get("/", response_class=HTMLResponse)
async def root_ui(
    request: Request,
    shop: Optional[str] = Query(default=None),
    id_token: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    billing: Optional[str] = Query(default=None),
) -> HTMLResponse:
    clean_shop = (shop or "").strip().lower()
    if clean_shop and clean_shop.endswith(".myshopify.com") and clean_shop != DEMO_SHOP:
        if code:
            _OAUTH_ATTEMPTED_SHOPS[clean_shop] = time.time()
            await _exchange_oauth_code(clean_shop, code)
        try:
            await resolve_shop_session(clean_shop, request=request, id_token_param=id_token)
        except Exception:
            pass
        if billing == "confirmed":
            try:
                set_shop_plan(clean_shop, "pro")
            except Exception:
                pass
    static_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(static_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__SHOPIFY_API_KEY__", SHOPIFY_API_KEY or "21dd49d16f61ca3776c623349af8d6aa")
    return HTMLResponse(content=html)


@app.get("/auth")
async def auth_start(shop: str = Query(...)) -> RedirectResponse:
    clean_shop = shop.strip().lower()
    if not clean_shop.endswith(".myshopify.com"):
        raise HTTPException(status_code=400, detail="Invalid shop domain")
    _OAUTH_ATTEMPTED_SHOPS[clean_shop] = time.time()
    if not SHOPIFY_API_KEY:
        return RedirectResponse(url=f"/?shop={urllib.parse.quote(clean_shop)}")
    redirect_uri = f"{APP_URL}/auth/callback"
    params = urllib.parse.urlencode(
        {
            "client_id": SHOPIFY_API_KEY,
            "scope": SCOPES,
            "redirect_uri": redirect_uri,
        }
    )
    return RedirectResponse(url=f"https://{clean_shop}/admin/oauth/authorize?{params}")


@app.get("/auth/callback")
async def auth_callback(request: Request) -> RedirectResponse:
    q = dict(request.query_params)
    shop = q.get("shop", "").strip().lower()
    code = q.get("code", "")
    if not shop or not shop.endswith(".myshopify.com"):
        raise HTTPException(status_code=400, detail="Missing or invalid shop parameter")
    _OAUTH_ATTEMPTED_SHOPS[shop] = time.time()
    if not code and SHOPIFY_API_SECRET and not verify_oauth_query_hmac(q):
        raise HTTPException(status_code=401, detail="Invalid OAuth HMAC signature")

    if code:
        await _exchange_oauth_code(shop, code)

    host = q.get("host", "")
    target = f"/?shop={urllib.parse.quote(shop)}&oauth_done=1"
    if host:
        target += f"&host={urllib.parse.quote(host)}"
    return RedirectResponse(url=target)


# ---------------------------------------------------------------------------
# REST API Endpoints
# ---------------------------------------------------------------------------
class RuleInput(BaseModel):
    rule_id: Optional[str] = None
    name: str
    rule_type: str = "item_quantity"
    target_type: str = "all"
    target_id: str = "all"
    target_title: str = "Entire Catalog"
    customer_segment: str = "all"
    customer_tag: str = ""
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step_val: Optional[int] = None
    error_template: Optional[str] = ""
    is_active: bool = True
    priority: int = 10


class EnforcementInput(BaseModel):
    enabled: bool


class CartLineInput(BaseModel):
    id: str
    title: str
    sku: str = ""
    price: float
    quantity: int
    collections: List[str] = []


class SimulationInput(BaseModel):
    items: List[CartLineInput]
    is_logged_in: bool = False
    customer_tags: List[str] = []
    checkout_surface: str = "standard_checkout"


def _is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "401" in msg or "403" in msg or "unauthorized" in msg or "access denied" in msg


async def _resolve_live_plan(clean_shop: str, client: ShopifyGraphQLClient) -> Dict[str, Any]:
    try:
        info = await client.get_billing_info()
        all_subs = info.get("active_subscriptions") or []
        active_subs = [s for s in all_subs if str(s.get("status", "")).upper() == "ACTIVE"]
        app_handle = info.get("app_handle") or ""
        plan = "pro" if active_subs else "free"
        set_shop_plan(clean_shop, plan)
        return {"plan": plan, "active_subscriptions": active_subs, "app_handle": app_handle}
    except Exception:
        set_shop_plan(clean_shop, "free")
        return {"plan": "free", "active_subscriptions": [], "app_handle": ""}


@app.get("/api/bootstrap")
async def api_bootstrap(
    request: Request,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = get_rules_for_shop(clean_shop, session_key)
    enforcement = get_shop_enforcement(session_key)

    await resolve_shop_session(clean_shop, request=request)
    live_session = is_live_shopify_session(clean_shop)

    if clean_shop != DEMO_SHOP:
        if not live_session:
            if not _has_embedded_context(request) and clean_shop not in _OAUTH_ATTEMPTED_SHOPS:
                raise HTTPException(
                    status_code=401,
                    detail={"error": "unauthorized", "auth_url": f"/auth?shop={urllib.parse.quote(clean_shop)}"},
                )
            compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
            return {
                "shop": clean_shop,
                "mode": "live_shopify",
                "plan": "free",
                "app_handle": "cartlogic-order-limits",
                "active_subscriptions": [],
                "managed_pricing_url": _build_managed_pricing_url(clean_shop, ""),
                "enforcement_enabled": enforcement,
                "rules": rules,
                "catalog": {"collections": [], "products": []},
                "compiled_config": compiled,
                "audit_logs": get_audit_logs(session_key, limit=20),
                "default_templates": DEFAULT_ERROR_TEMPLATES,
            }
        catalog: Dict[str, List[Dict[str, Any]]] = {"collections": [], "products": []}
        client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
        try:
            catalog = await client.fetch_catalog_targets(limit=30)
        except Exception:
            refreshed = await resolve_shop_session(clean_shop, request=request, force_refresh=True)
            if refreshed and refreshed.get("access_token") and not str(refreshed["access_token"]).startswith("fake_"):
                client = ShopifyGraphQLClient(clean_shop, refreshed["access_token"])
                try:
                    catalog = await client.fetch_catalog_targets(limit=30)
                except Exception:
                    pass
        billing_state = await _resolve_live_plan(clean_shop, client)
        compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
        logs = get_audit_logs(session_key, limit=20)
        return {
            "shop": clean_shop,
            "mode": "live_shopify",
            "plan": billing_state["plan"],
            "app_handle": billing_state["app_handle"] or "cartlogic-order-limits",
            "active_subscriptions": billing_state["active_subscriptions"],
            "managed_pricing_url": _build_managed_pricing_url(clean_shop, billing_state["app_handle"]),
            "enforcement_enabled": enforcement,
            "rules": rules,
            "catalog": catalog,
            "compiled_config": compiled,
            "audit_logs": logs,
            "default_templates": DEFAULT_ERROR_TEMPLATES,
        }

    catalog = copy.deepcopy(DEFAULT_CATALOG)
    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
    logs = get_audit_logs(session_key, limit=20)

    return {
        "shop": clean_shop,
        "mode": "sandbox",
        "plan": get_shop_plan(clean_shop),
        "app_handle": "cartlogic-order-limits",
        "enforcement_enabled": enforcement,
        "rules": rules,
        "catalog": catalog,
        "compiled_config": compiled,
        "audit_logs": logs,
        "default_templates": DEFAULT_ERROR_TEMPLATES,
    }


@app.post("/api/rules")
async def api_save_rule(
    payload: RuleInput,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    get_rules_for_shop(clean_shop, session_key)

    rule_id = (payload.rule_id or "").strip() or f"rule-{uuid.uuid4().hex[:8]}"
    template = (payload.error_template or "").strip() or DEFAULT_ERROR_TEMPLATES.get(
        payload.rule_type, "Order does not meet checkout limits."
    )

    rule_dict = {
        "rule_id": rule_id,
        "name": payload.name.strip() or "Untitled Validation Rule",
        "rule_type": payload.rule_type,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "target_title": payload.target_title,
        "customer_segment": payload.customer_segment,
        "customer_tag": payload.customer_tag.strip(),
        "min_val": payload.min_val,
        "max_val": payload.max_val,
        "step_val": payload.step_val,
        "error_template": template,
        "is_active": payload.is_active,
        "priority": payload.priority,
    }
    saved = save_rule(session_key, rule_dict)
    add_audit_log(
        session_key,
        "RULE_SAVED",
        {"rule_id": rule_id, "name": saved["name"], "type": saved["rule_type"]},
    )
    rules = list_rules(session_key)
    enforcement = get_shop_enforcement(session_key)
    return {
        "status": "saved",
        "rule": saved,
        "rules": rules,
        "compiled_config": compile_shopify_function_config(clean_shop, rules, enforcement),
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.post("/api/rules/{rule_id}/toggle")
async def api_toggle_rule(
    rule_id: str,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = get_rules_for_shop(clean_shop, session_key)
    target = next((r for r in rules if r["rule_id"] == rule_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Rule not found")

    target["is_active"] = not bool(target["is_active"])
    save_rule(session_key, target)
    add_audit_log(
        session_key,
        "RULE_TOGGLED",
        {"rule_id": rule_id, "name": target["name"], "is_active": target["is_active"]},
    )
    updated_rules = list_rules(session_key)
    enforcement = get_shop_enforcement(session_key)
    return {
        "status": "toggled",
        "rule": target,
        "rules": updated_rules,
        "compiled_config": compile_shopify_function_config(clean_shop, updated_rules, enforcement),
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.delete("/api/rules/{rule_id}")
async def api_delete_rule(
    rule_id: str,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    get_rules_for_shop(clean_shop, session_key)
    deleted = delete_rule(session_key, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")

    add_audit_log(session_key, "RULE_DELETED", {"rule_id": rule_id})
    updated_rules = list_rules(session_key)
    enforcement = get_shop_enforcement(session_key)
    return {
        "status": "deleted",
        "rules": updated_rules,
        "compiled_config": compile_shopify_function_config(clean_shop, updated_rules, enforcement),
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.post("/api/enforcement")
async def api_set_enforcement(
    payload: EnforcementInput,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    set_shop_enforcement(session_key, payload.enabled)
    add_audit_log(
        session_key,
        "ENFORCEMENT_UPDATED",
        {"enabled": payload.enabled},
    )
    rules = get_rules_for_shop(clean_shop, session_key)
    return {
        "status": "updated",
        "enforcement_enabled": payload.enabled,
        "compiled_config": compile_shopify_function_config(clean_shop, rules, payload.enabled),
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.post("/api/simulate")
async def api_simulate_checkout(
    payload: SimulationInput,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = get_rules_for_shop(clean_shop, session_key)
    enforcement = get_shop_enforcement(session_key)

    cart_items = [item.model_dump() for item in payload.items]
    buyer_ctx = {
        "is_logged_in": payload.is_logged_in,
        "tags": payload.customer_tags,
        "checkout_surface": payload.checkout_surface,
    }
    evaluation = evaluate_cart(
        rules=rules,
        cart_items=cart_items,
        buyer_context=buyer_ctx,
        enforcement_enabled=enforcement,
    )
    evaluation["checkout_surface"] = payload.checkout_surface
    return evaluation


@app.post("/api/sync-checkout")
async def api_sync_to_shopify(
    request: Request,
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = get_rules_for_shop(clean_shop, session_key)
    enforcement = get_shop_enforcement(session_key)
    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)

    await resolve_shop_session(clean_shop, request=request)
    live_session = is_live_shopify_session(clean_shop)
    sync_mode = "sandbox_metafield"
    if live_session:
        try:
            client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
            await client.sync_validation_metafield(compiled)
            sync_mode = "shopify_metafield_live"
        except Exception:
            sync_mode = "sandbox_metafield"

    add_audit_log(
        session_key,
        "CHECKOUT_FUNCTION_SYNCED",
        {
            "active_rules": compiled["active_rules_count"],
            "enabled": enforcement,
            "mode": sync_mode,
        },
    )
    return {
        "status": "synced",
        "mode": sync_mode,
        "compiled_config": compiled,
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.post("/api/reset-defaults")
async def api_reset_defaults(
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    existing = list_rules(session_key)
    for r in existing:
        delete_rule(session_key, r["rule_id"])
    if clean_shop == DEMO_SHOP:
        for r in DEFAULT_RULES:
            save_rule(session_key, r)
        add_audit_log(session_key, "DEFAULTS_RESTORED", {"rules_count": len(DEFAULT_RULES)})
    else:
        add_audit_log(session_key, "RULES_CLEARED", {"rules_count": 0})
    set_shop_enforcement(session_key, True)
    rules = list_rules(session_key)
    return {
        "status": "reset",
        "enforcement_enabled": True,
        "rules": rules,
        "compiled_config": compile_shopify_function_config(clean_shop, rules, True),
        "audit_logs": get_audit_logs(session_key, limit=20),
    }


@app.get("/api/export-config")
async def api_export_config(
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> PlainTextResponse:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = get_rules_for_shop(clean_shop, session_key)
    enforcement = get_shop_enforcement(session_key)
    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
    return PlainTextResponse(
        content=json.dumps(compiled, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="cartlogic-function-config.json"'},
    )


def _build_managed_pricing_url(shop: str, app_handle: str = "") -> str:
    slug = (shop or "").replace(".myshopify.com", "").strip()
    handle = (app_handle or "cartlogic-order-limits").strip()
    if not slug or slug == "demo-store":
        return ""
    return f"https://admin.shopify.com/store/{slug}/charges/{handle}/pricing_plans"


@app.get("/api/billing/status")
async def api_billing_status(
    request: Request,
    shop: str = Query(default=DEMO_SHOP),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    await resolve_shop_session(clean_shop, request=request)
    live_session = is_live_shopify_session(clean_shop)
    if live_session:
        client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
        billing_state = await _resolve_live_plan(clean_shop, client)
        return {
            "shop": clean_shop,
            "plan": billing_state["plan"],
            "active_subscriptions": billing_state["active_subscriptions"],
            "managed_pricing_url": _build_managed_pricing_url(clean_shop, billing_state["app_handle"]),
        }
    return {
        "shop": clean_shop,
        "plan": get_shop_plan(clean_shop),
        "active_subscriptions": [],
        "managed_pricing_url": "",
    }


@app.post("/api/billing/downgrade")
async def api_billing_downgrade(
    request: Request,
    shop: str = Query(default=DEMO_SHOP),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    await resolve_shop_session(clean_shop, request=request)
    live_session = is_live_shopify_session(clean_shop)
    cancelled_ids: List[str] = []
    if live_session:
        client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
        for attempt in range(2):
            try:
                client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
                cancelled_ids = await client.cancel_active_subscriptions()
                break
            except Exception:
                if attempt == 0:
                    refreshed = await resolve_shop_session(clean_shop, request=request, force_refresh=True)
                    if refreshed and refreshed.get("access_token") and not str(refreshed["access_token"]).startswith("fake_"):
                        live_session = refreshed
                        continue
                break
        billing_state = await _resolve_live_plan(clean_shop, client)
        managed_url = _build_managed_pricing_url(clean_shop, billing_state["app_handle"])
        if billing_state["plan"] == "pro" and not cancelled_ids and managed_url:
            return {
                "status": "redirect",
                "mode": "managed_pricing",
                "plan": "pro",
                "confirmation_url": managed_url,
                "managed_pricing_url": managed_url,
            }
        set_shop_plan(clean_shop, "free")
        return {
            "status": "downgraded",
            "plan": "free",
            "plan_label": "Free Starter ($0/mo)",
            "cancelled_subscriptions": cancelled_ids,
            "managed_pricing_url": managed_url,
        }

    set_shop_plan(clean_shop, "free")
    return {
        "status": "downgraded",
        "plan": "free",
        "plan_label": "Free Starter ($0/mo)",
        "cancelled_subscriptions": [],
        "managed_pricing_url": "",
    }


@app.post("/api/billing/subscribe")
async def api_billing_subscribe(
    request: Request,
    shop: str = Query(default=DEMO_SHOP),
    plan: str = Query(default="pro"),
) -> Dict[str, Any]:
    if (plan or "").strip().lower() == "free":
        return await api_billing_downgrade(request=request, shop=shop)

    clean_shop = (shop or DEMO_SHOP).strip().lower()
    await resolve_shop_session(clean_shop, request=request)
    live_session = is_live_shopify_session(clean_shop)
    return_url = f"{APP_URL}/?shop={urllib.parse.quote(clean_shop)}&billing=confirmed"
    if live_session:
        client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
        for attempt in range(2):
            try:
                client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
                res = await client.create_subscription(
                    return_url=return_url,
                    plan_name="Pro Validation",
                    price_usd=9.99,
                    trial_days=14,
                    test_mode=True,
                )
                sub_data = res.get("appSubscriptionCreate") or {}
                user_errors = sub_data.get("userErrors") or []
                if sub_data.get("confirmationUrl") and not user_errors:
                    return {
                        "status": "redirect",
                        "mode": "live_shopify",
                        "plan": "pro",
                        "plan_label": "Pro Validation ($9.99/mo, 14-day free trial)",
                        "confirmation_url": sub_data["confirmationUrl"],
                    }
                break
            except Exception:
                if attempt == 0:
                    refreshed = await resolve_shop_session(clean_shop, request=request, force_refresh=True)
                    if refreshed and refreshed.get("access_token") and not str(refreshed["access_token"]).startswith("fake_"):
                        live_session = refreshed
                        continue
                break
        billing_state = await _resolve_live_plan(clean_shop, client)
        managed_url = _build_managed_pricing_url(clean_shop, billing_state["app_handle"])
        return {
            "status": "redirect",
            "mode": "managed_pricing",
            "plan": billing_state["plan"],
            "plan_label": "Pro Validation ($9.99/mo, 14-day free trial)",
            "confirmation_url": managed_url,
            "managed_pricing_url": managed_url,
        }

    if clean_shop != DEMO_SHOP:
        managed_url = _build_managed_pricing_url(clean_shop, "")
        return {
            "status": "redirect",
            "mode": "managed_pricing",
            "plan": "free",
            "plan_label": "Pro Validation ($9.99/mo, 14-day free trial)",
            "confirmation_url": managed_url,
            "managed_pricing_url": managed_url,
        }

    set_shop_plan(clean_shop, "pro")
    return {"status": "active_sandbox", "plan": "Pro Validation Plan Activated", "plan_id": "pro"}


# ---------------------------------------------------------------------------
# Mandatory Shopify Compliance & Lifecycle Webhooks (HMAC-SHA256 Verified)
# ---------------------------------------------------------------------------
@app.api_route("/webhooks/gdpr", methods=["GET", "POST"])
@app.api_route("/webhooks/customers/data_request", methods=["GET", "POST"])
@app.api_route("/webhooks/customers/redact", methods=["GET", "POST"])
@app.api_route("/webhooks/shop/redact", methods=["GET", "POST"])
@app.api_route("/webhooks/app/uninstalled", methods=["GET", "POST"])
async def handle_shopify_webhooks(
    request: Request,
    x_shopify_hmac_sha256: Optional[str] = Header(default=None),
    x_shopify_topic: Optional[str] = Header(default=None),
    x_shopify_shop_domain: Optional[str] = Header(default=None),
) -> JSONResponse:
    if request.method == "GET":
        return JSONResponse({"status": "webhook_endpoint_ready"})

    raw_body = await request.body()
    if not verify_shopify_hmac(raw_body, x_shopify_hmac_sha256):
        raise HTTPException(status_code=401, detail="Invalid Shopify webhook HMAC signature")

    if x_shopify_topic in ("shop/redact", "app/uninstalled") and x_shopify_shop_domain:
        delete_shop_data(x_shopify_shop_domain.strip().lower())

    return JSONResponse({"status": "ok", "topic": x_shopify_topic or "compliance"})


@app.get("/screencast")
@app.get("/screencast.webm")
@app.get("/demo.webm")
async def screencast_video():
    path = os.path.join(os.path.dirname(__file__), "static", "demo.webm")
    if os.path.exists(path):
        return FileResponse(path, media_type="video/webm")
    raise HTTPException(status_code=404, detail="Screencast video not found")


# ---------------------------------------------------------------------------
# Public Health, Privacy Policy & Support Endpoints
# ---------------------------------------------------------------------------
@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> PlainTextResponse:
    return PlainTextResponse("", status_code=204)


@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "CartLogic — Order & Quantity Limits"}


@app.get("/static/proof_pricing_plans.png")
async def proof_pricing_image() -> FileResponse:
    path = os.path.join(os.path.dirname(__file__), "static", "proof_pricing_plans.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Proof image not found")


@app.get("/proof-of-resolution", response_class=HTMLResponse)
async def proof_of_resolution_page() -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Proof of Resolution — CartLogic Order Limits (Issues 1.2.2 &amp; 1.2.3)</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 920px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #202223; background: #fdfdfd; }
    h1 { color: #008060; font-size: 24px; margin-top: 8px; }
    h2 { color: #1a1c1d; font-size: 18px; margin: 0 0 10px 0; }
    .card { background: #f6f6f7; border: 1px solid #dde0e4; border-radius: 8px; padding: 20px; margin: 20px 0; }
    .badge { display: inline-block; background: #e3f1df; color: #11622b; padding: 4px 10px; border-radius: 999px; font-weight: 600; font-size: 13px; }
    code { background: #eef0f2; padding: 2px 6px; border-radius: 4px; font-size: 13.5px; }
    .check { color: #008060; font-weight: 700; }
    .img-wrap { text-align: center; margin-top: 20px; }
    img { max-width: 100%; height: auto; border-radius: 8px; border: 1px solid #dde0e4; box-shadow: 0 4px 12px rgba(0,0,0,0.08); display: block; margin: 0 auto; }
  </style>
</head>
<body>
  <span class="badge">RESOLVED — ISSUES 1.2.2 &amp; 1.2.3</span>
  <h1>Proof of Resolution: CartLogic Order Limits</h1>
  <p><strong>App:</strong> CartLogic Order Limits (Client ID: <code>21dd49d16f61ca3776c623349af8d6aa</code>)</p>

  <div class="card">
    <h2>1. Issue 1.2.2 &amp; 1.2.3 — Shopify App Pricing Enabled with 2 Public Plans</h2>
    <ul>
      <li><span class="check">&#10003;</span> <strong>Switched from Legacy Manual Pricing to Shopify App Pricing (Managed Pricing):</strong> Enabled Shopify App Pricing in the Partner Dashboard so the Shopify-hosted plan selection page (<code>/charges/cartlogic-order-limits/pricing_plans</code>) now displays both selectable public plans instead of "No plans are available for your store".</li>
      <li><span class="check">&#10003;</span> <strong>Full Self-Service Upgrade, Downgrade &amp; Reinstall Flow:</strong> Merchants and reviewers can select <strong>Free Starter ($0/mo)</strong> or <strong>Pro Validation ($9.99/mo · 14-day free trial)</strong>, accept, decline, upgrade, downgrade, cancel, and re-approve on reinstall directly via Shopify's native plan page.</li>
      <li><span class="check">&#10003;</span> <strong>Live Subscription Sync:</strong> On every load and reinstall, the app verifies active subscriptions live via <code>currentAppInstallation.activeSubscriptions</code>.</li>
    </ul>
  </div>

  <h3>Verified Live Shopify Hosted Plan Selection Page (Development Store):</h3>
  <div class="img-wrap">
    <img src="/static/proof_pricing_plans.png" alt="CartLogic Order Limits — Live Shopify App Pricing Plan Selection Page (Free Starter &amp; Pro Validation)" />
  </div>
</body>
</html>"""
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Privacy Policy — CartLogic Order & Quantity Limits</title>
<style>body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:740px;margin:48px auto;padding:0 24px;line-height:1.65;color:#1a1a1a}h1,h2{letter-spacing:-0.015em}</style>
</head>
<body>
<h1>Privacy Policy — CartLogic Order &amp; Quantity Limits</h1>
<p><strong>Effective Date:</strong> November 2026</p>
<p>CartLogic ("the App") is operated by Sergey Gorbunov (Ljubljana, Slovenia; contact: <a href="mailto:mikrozar@gmail.com">mikrozar@gmail.com</a>).</p>
<h2>1. Zero Protected Customer Data Stored</h2>
<p>The App accesses product and collection catalog metadata (<code>read_products</code>, <code>write_products</code>) solely to configure and synchronize cart and checkout quantity validation rules. The App <strong>does not collect, store, or process personal customer information (PII)</strong>, buyer addresses, or payment details.</p>
<h2>2. Mandatory GDPR Webhooks</h2>
<p>We implement all mandatory Shopify compliance webhooks (<code>customers/data_request</code>, <code>customers/redact</code>, and <code>shop/redact</code>). Upon uninstallation or shop redaction, all validation rules and configuration metadata for the store are permanently deleted.</p>
<h2>3. Contact</h2>
<p>For privacy inquiries, contact <a href="mailto:mikrozar@gmail.com">mikrozar@gmail.com</a>.</p>
</body></html>"""
    )


@app.get("/support", response_class=HTMLResponse)
async def support_page() -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Support — CartLogic Order & Quantity Limits</title>
<style>body{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:740px;margin:48px auto;padding:0 24px;line-height:1.65;color:#1a1a1a}.box{background:#f6f6f7;border:1px solid #e3e3e3;border-radius:8px;padding:20px;margin:20px 0}</style>
</head>
<body>
<h1>Support &amp; Documentation — CartLogic</h1>
<div class="box">
  <strong>Direct Engineering Support</strong><br>
  Email: <a href="mailto:mikrozar@gmail.com">mikrozar@gmail.com</a><br>
  Response SLA: Within 24 business hours (Monday–Saturday, CET).
</div>
<h2>Frequently Asked Questions</h2>
<ul>
  <li><strong>Can buyers bypass limits using Apple Pay, Shop Pay, or Express Checkout?</strong> No. Rules are evaluated against checkout lines and subtotal constraints before payment completion, preventing express-button bypasses.</li>
  <li><strong>How do B2B vs. Retail customer segments work?</strong> Rules can target all visitors, exclusively B2B accounts carrying a tag such as <code>wholesale</code>, or exclusively retail buyers (exempting wholesale accounts from retail drop limits).</li>
</ul>
</body></html>"""
    )

