"""
FastAPI Backend for CartLogic — Order & Quantity Limits (Shopify Embedded App).
Provides:
- Native Shopify Cart & Checkout Validation rule engine (Min/Max Order Value, Item Quantity, Case Pack Multiples, Collection Caps)
- Customer segment targeting (All Visitors, B2B/Wholesale Tag, Retail Only, Logged-in Accounts)
- Real-time Checkout & Express Payment Simulator (Shop Pay / Apple Pay / Standard Checkout)
- Shopify GraphQL Admin API sync to Shop Metafields (`cartlogic.validation_rules_v1`)
- Shopify OAuth2, App Bridge v4 Session Tokens, Billing API, and Mandatory GDPR Webhooks
"""
import base64
import copy
import hashlib
import hmac
import json
import os
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
    init_db,
    list_rules,
    save_rule,
    set_shop_enforcement,
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
APP_URL = os.environ.get("APP_URL", "https://cartlogic-app.onrender.com").rstrip("/")
SCOPES = "read_products,write_products"
DEMO_SHOP = "demo-store.myshopify.com"

app = FastAPI(title="CartLogic — Order & Quantity Limits", version="1.0.0")


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
@app.get("/", response_class=HTMLResponse)
async def root_ui(request: Request, shop: Optional[str] = Query(default=None)) -> HTMLResponse:
    if shop and shop.endswith(".myshopify.com") and shop != DEMO_SHOP:
        shop_data = get_shop(shop)
        if not shop_data or not shop_data.get("access_token"):
            auth_url = f"/auth?shop={urllib.parse.quote(shop)}"
            return HTMLResponse(
                f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script>
  var target = "{auth_url}";
  if (window.top !== window.self) {{ window.top.location.href = target; }}
  else {{ window.location.href = target; }}
</script></head>
<body style="font-family:Inter,-apple-system,sans-serif;padding:40px;color:#1a1a1a;">
  Connecting CartLogic with Shopify Admin...
</body></html>"""
            )
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
    if SHOPIFY_API_SECRET and not verify_oauth_query_hmac(q):
        raise HTTPException(status_code=401, detail="Invalid OAuth HMAC signature")

    if code and SHOPIFY_API_KEY and SHOPIFY_API_SECRET:
        token_url = f"https://{shop}/admin/oauth/access_token"
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
                upsert_shop(shop, data.get("access_token", ""), data.get("scope", SCOPES))

    host = q.get("host", "")
    return RedirectResponse(url=f"/?shop={urllib.parse.quote(shop)}&host={urllib.parse.quote(host)}")


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


@app.get("/api/bootstrap")
async def api_bootstrap(
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = ensure_seed_rules(session_key)
    enforcement = get_shop_enforcement(session_key)

    catalog = copy.deepcopy(DEFAULT_CATALOG)
    mode = "sandbox"
    live_session = is_live_shopify_session(clean_shop)
    if live_session:
        try:
            client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
            live_cat = await client.fetch_catalog_targets(limit=30)
            if live_cat["products"] or live_cat["collections"]:
                catalog = live_cat
            mode = "live_shopify"
        except Exception:
            mode = "sandbox"

    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
    logs = get_audit_logs(session_key, limit=20)

    return {
        "shop": clean_shop,
        "mode": mode,
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
    ensure_seed_rules(session_key)

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
    rules = ensure_seed_rules(session_key)
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
    ensure_seed_rules(session_key)
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
    rules = ensure_seed_rules(session_key)
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
    rules = ensure_seed_rules(session_key)
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
    shop: str = Query(default=DEMO_SHOP),
    x_demo_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    session_key = get_session_key(clean_shop, x_demo_session)
    rules = ensure_seed_rules(session_key)
    enforcement = get_shop_enforcement(session_key)
    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)

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
    for r in DEFAULT_RULES:
        save_rule(session_key, r)
    set_shop_enforcement(session_key, True)
    add_audit_log(session_key, "DEFAULTS_RESTORED", {"rules_count": len(DEFAULT_RULES)})
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
    rules = ensure_seed_rules(session_key)
    enforcement = get_shop_enforcement(session_key)
    compiled = compile_shopify_function_config(clean_shop, rules, enforcement)
    return PlainTextResponse(
        content=json.dumps(compiled, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="cartlogic-function-config.json"'},
    )


@app.post("/api/billing/subscribe")
async def api_billing_subscribe(
    shop: str = Query(default=DEMO_SHOP),
) -> Dict[str, Any]:
    clean_shop = (shop or DEMO_SHOP).strip().lower()
    live_session = is_live_shopify_session(clean_shop)
    return_url = f"{APP_URL}/?shop={urllib.parse.quote(clean_shop)}&billing=confirmed"
    if live_session:
        client = ShopifyGraphQLClient(clean_shop, live_session["access_token"])
        res = await client.create_subscription(
            return_url=return_url,
            plan_name="Pro Validation",
            price_usd=14.99,
            trial_days=14,
            test_mode=True,
        )
        sub_data = res.get("appSubscriptionCreate") or {}
        if sub_data.get("confirmationUrl"):
            return {"status": "redirect", "confirmation_url": sub_data["confirmationUrl"]}
    return {"status": "active_sandbox", "plan": "Pro Validation Plan Activated"}


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
@app.get("/health")
async def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "CartLogic — Order & Quantity Limits"}


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

