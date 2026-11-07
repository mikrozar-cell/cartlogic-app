"""
Comprehensive Automated Test Suite for CartLogic — Order & Quantity Limits.
Tests all 5 validation rule types, B2B/Retail customer segment filtering,
Shopify Functions schema compilation, FastAPI endpoints, and GDPR HMAC security.
"""
import base64
import hashlib
import hmac
import os
import tempfile
from fastapi.testclient import TestClient

# Point SQLite to an isolated temp file before importing app modules
_TEMP_DB = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_TEMP_DB.close()
os.environ["CARTLIMITS_DB_PATH"] = _TEMP_DB.name

from app.database import init_db
from app.server import app, SHOPIFY_API_SECRET
from app.validation_engine import (
    compile_shopify_function_config,
    evaluate_cart,
    matches_customer_segment,
)

init_db()
client = TestClient(app)


def test_step_multiple_validation():
    rules = [
        {
            "rule_id": "r-step-6",
            "name": "Cold Brew Case Pack of 6",
            "rule_type": "step_multiple",
            "target_type": "product",
            "target_id": "prod-1",
            "target_title": "Cold Brew 1L",
            "customer_segment": "all",
            "step_val": 6,
            "error_template": "{item_title} requires multiples of {step} (you have {current}, add {shortfall}).",
            "is_active": True,
            "priority": 1,
        }
    ]
    # 4 units -> should block checkout and ask for 2 more
    res_fail = evaluate_cart(
        rules,
        [{"id": "prod-1", "title": "Cold Brew 1L", "sku": "CB-1", "price": 18.0, "quantity": 4}],
    )
    assert res_fail["checkout_blocked"] is True
    assert len(res_fail["violations"]) == 1
    assert "multiples of 6 (you have 4, add 2)" in res_fail["violations"][0]["message"]

    # 12 units -> valid
    res_ok = evaluate_cart(
        rules,
        [{"id": "prod-1", "title": "Cold Brew 1L", "sku": "CB-1", "price": 18.0, "quantity": 12}],
    )
    assert res_ok["checkout_blocked"] is False
    assert res_ok["valid"] is True


def test_b2b_vs_retail_segment_exemption():
    rules = [
        {
            "rule_id": "r-drop-max2",
            "name": "Limited Drop Max 2",
            "rule_type": "item_quantity",
            "target_type": "product",
            "target_id": "prod-watch",
            "target_title": "Titanium Watch",
            "customer_segment": "retail_only",
            "customer_tag": "wholesale",
            "min_val": 1,
            "max_val": 2,
            "error_template": "Max {max} allowed for retail.",
            "is_active": True,
            "priority": 1,
        },
        {
            "rule_id": "r-b2b-min-subtotal",
            "name": "B2B Min Order €500",
            "rule_type": "cart_value",
            "target_type": "all",
            "target_id": "all",
            "target_title": "Entire Cart",
            "customer_segment": "b2b_only",
            "customer_tag": "wholesale",
            "min_val": 500.0,
            "max_val": None,
            "error_template": "B2B min €{min} required.",
            "is_active": True,
            "priority": 2,
        },
    ]
    cart_3_watches = [
        {"id": "prod-watch", "title": "Titanium Watch", "sku": "WT-1", "price": 100.0, "quantity": 3}
    ]

    # Retail buyer buying 3 watches (€300): blocked by retail Max 2 rule, exempt from B2B €500 rule
    retail_eval = evaluate_cart(rules, cart_3_watches, {"is_logged_in": False, "tags": []})
    assert retail_eval["checkout_blocked"] is True
    assert len(retail_eval["violations"]) == 1
    assert retail_eval["violations"][0]["rule_id"] == "r-drop-max2"

    # B2B buyer buying 3 watches (€300): exempt from retail Max 2 rule, blocked by B2B Min €500 rule
    b2b_eval = evaluate_cart(rules, cart_3_watches, {"is_logged_in": True, "tags": ["wholesale"]})
    assert b2b_eval["checkout_blocked"] is True
    assert len(b2b_eval["violations"]) == 1
    assert b2b_eval["violations"][0]["rule_id"] == "r-b2b-min-subtotal"

    # B2B buyer buying 6 watches (€600): passes all rules!
    cart_6_watches = [
        {"id": "prod-watch", "title": "Titanium Watch", "sku": "WT-1", "price": 100.0, "quantity": 6}
    ]
    b2b_pass = evaluate_cart(rules, cart_6_watches, {"is_logged_in": True, "tags": ["wholesale"]})
    assert b2b_pass["checkout_blocked"] is False


def test_collection_limit_and_compiled_schema():
    rules = [
        {
            "rule_id": "r-col-cap",
            "name": "Sample Cap",
            "rule_type": "collection_limit",
            "target_type": "collection",
            "target_id": "col-samples",
            "target_title": "Samples",
            "customer_segment": "all",
            "min_val": 1,
            "max_val": 4,
            "is_active": True,
            "priority": 1,
        }
    ]
    cart = [
        {
            "id": "p1",
            "title": "Sample A",
            "price": 10.0,
            "quantity": 3,
            "collections": ["col-samples"],
        },
        {
            "id": "p2",
            "title": "Sample B",
            "price": 10.0,
            "quantity": 2,
            "collections": ["col-samples"],
        },
    ]
    res = evaluate_cart(rules, cart)
    assert res["checkout_blocked"] is True
    assert res["violations"][0]["current"] == 5

    compiled = compile_shopify_function_config("test.myshopify.com", rules, True)
    assert compiled["schema"] == "shopify.functions.cart-checkout-validation.v1"
    assert compiled["active_rules_count"] == 1


def test_api_bootstrap_crud_and_simulation():
    headers = {"X-Demo-Session": "pytest_session_01"}
    r_boot = client.get("/api/bootstrap", headers=headers)
    assert r_boot.status_code == 200
    data = r_boot.json()
    assert len(data["rules"]) == 4

    # Create a new cart_quantity rule
    r_create = client.post(
        "/api/rules",
        headers=headers,
        json={
            "name": "Max 50 Total Units",
            "rule_type": "cart_quantity",
            "target_type": "all",
            "target_id": "all",
            "target_title": "Entire Cart",
            "customer_segment": "all",
            "min_val": 1,
            "max_val": 50,
            "is_active": True,
            "priority": 5,
        },
    )
    assert r_create.status_code == 200
    new_rule_id = r_create.json()["rule"]["rule_id"]
    assert len(r_create.json()["rules"]) == 5

    # Toggle the rule off
    r_toggle = client.post(f"/api/rules/{new_rule_id}/toggle", headers=headers)
    assert r_toggle.status_code == 200
    assert r_toggle.json()["rule"]["is_active"] is False

    # Delete the rule
    r_del = client.delete(f"/api/rules/{new_rule_id}", headers=headers)
    assert r_del.status_code == 200
    assert len(r_del.json()["rules"]) == 4

    # Simulate cart
    r_sim = client.post(
        "/api/simulate",
        headers=headers,
        json={
            "items": [
                {
                    "id": "gid://shopify/Product/501",
                    "title": "Nitro Cold Brew Concentrate — Commercial 1L",
                    "sku": "NCB-1000",
                    "price": 18.0,
                    "quantity": 4,
                    "collections": ["col-wholesale-beverages"],
                }
            ],
            "is_logged_in": False,
            "customer_tags": [],
            "checkout_surface": "shop_pay_express",
        },
    )
    assert r_sim.status_code == 200
    assert r_sim.json()["checkout_blocked"] is True


def test_gdpr_webhook_hmac_verification():
    # Reject invalid HMAC
    r_bad = client.post(
        "/webhooks/customers/redact",
        content=b'{"shop_domain":"test.myshopify.com"}',
        headers={"X-Shopify-Hmac-Sha256": "invalid_signature"},
    )
    assert r_bad.status_code == 401

    # Accept valid HMAC
    secret = SHOPIFY_API_SECRET or "cartlogic_default_secret"
    body = b'{"shop_domain":"test.myshopify.com"}'
    sig = base64.b64encode(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()).decode("utf-8")
    r_ok = client.post(
        "/webhooks/shop/redact",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": sig,
            "X-Shopify-Topic": "shop/redact",
            "X-Shopify-Shop-Domain": "test.myshopify.com",
        },
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["status"] == "ok"
