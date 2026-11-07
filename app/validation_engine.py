"""
Pure-Function Cart & Checkout Validation Engine for CartLogic.
Simulates and compiles rules compatible with Shopify Cart & Checkout Validation API (Shopify Functions).
"""
from typing import Any, Dict, List, Optional


DEFAULT_ERROR_TEMPLATES: Dict[str, str] = {
    "cart_value": "Order subtotal must be between €{min} and €{max} (current cart: €{current}).",
    "cart_quantity": "Total cart quantity must be between {min} and {max} units (current: {current} units).",
    "item_quantity": "{item_title}: allowed quantity is {min} to {max} units per order (you have {current}).",
    "step_multiple": "{item_title} is sold in case packs of {step} units (you have {current} — add {shortfall} more).",
    "collection_limit": "Collection '{target_title}' requires between {min} and {max} total units (current: {current}).",
}


def matches_customer_segment(
    rule: Dict[str, Any],
    buyer_context: Dict[str, Any],
) -> bool:
    """
    Evaluate whether a validation rule applies to the current buyer context.
    buyer_context: {
        "is_logged_in": bool,
        "tags": List[str], # e.g. ["b2b", "wholesale", "vip"]
    }
    """
    segment = (rule.get("customer_segment") or "all").strip().lower()
    raw_tags = buyer_context.get("tags") or []
    buyer_tags = {str(t).strip().lower() for t in raw_tags if str(t).strip()}
    is_logged_in = bool(buyer_context.get("is_logged_in", False))
    rule_tag = (rule.get("customer_tag") or "b2b").strip().lower()

    if segment == "all":
        return True
    if segment == "b2b_only":
        return rule_tag in buyer_tags or "b2b" in buyer_tags or "wholesale" in buyer_tags
    if segment == "retail_only":
        is_b2b = rule_tag in buyer_tags or "b2b" in buyer_tags or "wholesale" in buyer_tags
        return not is_b2b
    if segment == "logged_in":
        return is_logged_in
    if segment == "custom_tag":
        return bool(rule_tag and rule_tag in buyer_tags)
    return True


def format_error_message(
    template: str,
    rule_type: str,
    context: Dict[str, Any],
) -> str:
    """Interpolate placeholders cleanly without throwing KeyError."""
    raw = (template or "").strip() or DEFAULT_ERROR_TEMPLATES.get(
        rule_type, "Order does not meet store checkout limits."
    )
    safe_ctx = {
        "min": context.get("min", ""),
        "max": context.get("max", ""),
        "step": context.get("step", ""),
        "current": context.get("current", ""),
        "shortfall": context.get("shortfall", ""),
        "excess": context.get("excess", ""),
        "item_title": context.get("item_title", "Selected item"),
        "target_title": context.get("target_title", "Selected collection"),
        "sku": context.get("sku", ""),
    }
    msg = raw
    for k, v in safe_ctx.items():
        msg = msg.replace("{" + k + "}", str(v))
    return msg


def evaluate_cart(
    rules: List[Dict[str, Any]],
    cart_items: List[Dict[str, Any]],
    buyer_context: Optional[Dict[str, Any]] = None,
    enforcement_enabled: bool = True,
) -> Dict[str, Any]:
    """
    Validate a shopping cart against all active rules.
    Returns both the native Shopify Functions schema (`errors`) and detailed diagnostics.
    """
    buyer = buyer_context or {"is_logged_in": False, "tags": []}
    active_items = [item for item in cart_items if int(item.get("quantity", 0)) > 0]

    cart_subtotal = round(
        sum(float(i.get("price", 0.0)) * int(i.get("quantity", 0)) for i in active_items),
        2,
    )
    cart_total_qty = sum(int(i.get("quantity", 0)) for i in active_items)

    shopify_errors: List[Dict[str, str]] = []
    violations: List[Dict[str, Any]] = []
    passed_rules: List[Dict[str, Any]] = []

    if not enforcement_enabled:
        return {
            "valid": True,
            "checkout_blocked": False,
            "enforcement_enabled": False,
            "cart_subtotal": cart_subtotal,
            "cart_total_quantity": cart_total_qty,
            "errors": [],
            "violations": [],
            "passed_rules": [],
        }

    sorted_rules = sorted(
        [r for r in rules if r.get("is_active", True)],
        key=lambda x: int(x.get("priority", 10)),
    )

    for rule in sorted_rules:
        if not matches_customer_segment(rule, buyer):
            continue

        rtype = (rule.get("rule_type") or "item_quantity").strip().lower()
        target_type = (rule.get("target_type") or "all").strip().lower()
        target_id = str(rule.get("target_id") or "all").strip()
        target_title = rule.get("target_title") or "Entire Catalog"
        min_val = rule.get("min_val")
        max_val = rule.get("max_val")
        step_val = rule.get("step_val")
        template = rule.get("error_template") or ""

        rule_violated = False

        # 1. Cart Subtotal Order Limit (EUR / USD)
        if rtype == "cart_value":
            if min_val is not None and float(min_val) > 0 and cart_subtotal < float(min_val):
                shortfall = round(float(min_val) - cart_subtotal, 2)
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": f"{float(min_val):.2f}",
                        "max": f"{float(max_val):.2f}" if max_val else "∞",
                        "current": f"{cart_subtotal:.2f}",
                        "shortfall": f"{shortfall:.2f}",
                        "target_title": target_title,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Cart Value Limit"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": cart_subtotal,
                        "required_min": float(min_val),
                        "required_max": float(max_val) if max_val else None,
                        "remediation": f"Add €{shortfall:.2f} more to proceed to checkout.",
                    }
                )
                rule_violated = True
            elif max_val is not None and float(max_val) > 0 and cart_subtotal > float(max_val):
                excess = round(cart_subtotal - float(max_val), 2)
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": f"{float(min_val):.2f}" if min_val else "0.00",
                        "max": f"{float(max_val):.2f}",
                        "current": f"{cart_subtotal:.2f}",
                        "excess": f"{excess:.2f}",
                        "target_title": target_title,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Cart Value Maximum"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": cart_subtotal,
                        "required_min": float(min_val) if min_val else None,
                        "required_max": float(max_val),
                        "remediation": f"Reduce cart subtotal by €{excess:.2f} (maximum allowed is €{float(max_val):.2f}).",
                    }
                )
                rule_violated = True

        # 2. Total Cart Quantity Limit
        elif rtype == "cart_quantity":
            min_q = int(min_val) if min_val is not None and float(min_val) > 0 else None
            max_q = int(max_val) if max_val is not None and float(max_val) > 0 else None
            if min_q is not None and cart_total_qty < min_q:
                shortfall = min_q - cart_total_qty
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": min_q,
                        "max": max_q if max_q else "∞",
                        "current": cart_total_qty,
                        "shortfall": shortfall,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Total Cart Units Limit"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": cart_total_qty,
                        "required_min": min_q,
                        "required_max": max_q,
                        "remediation": f"Add {shortfall} more unit(s) to cart.",
                    }
                )
                rule_violated = True
            elif max_q is not None and cart_total_qty > max_q:
                excess = cart_total_qty - max_q
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": min_q if min_q else 1,
                        "max": max_q,
                        "current": cart_total_qty,
                        "excess": excess,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Total Cart Units Limit"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": cart_total_qty,
                        "required_min": min_q,
                        "required_max": max_q,
                        "remediation": f"Remove {excess} unit(s) from cart (max {max_q} allowed).",
                    }
                )
                rule_violated = True

        # 3. Per-Product / SKU Quantity Limit
        elif rtype == "item_quantity":
            min_q = int(min_val) if min_val is not None and float(min_val) > 0 else None
            max_q = int(max_val) if max_val is not None and float(max_val) > 0 else None
            for item in active_items:
                if not _item_matches_target(item, target_type, target_id):
                    continue
                iqty = int(item.get("quantity", 0))
                if min_q is not None and iqty < min_q:
                    shortfall = min_q - iqty
                    msg = format_error_message(
                        template,
                        rtype,
                        {
                            "min": min_q,
                            "max": max_q if max_q else "∞",
                            "current": iqty,
                            "shortfall": shortfall,
                            "item_title": item.get("title", "Item"),
                            "sku": item.get("sku", ""),
                        },
                    )
                    shopify_errors.append({"localizedMessage": msg, "target": "$.cart.lines"})
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule.get("name", "Per-Item Minimum"),
                            "rule_type": rtype,
                            "target": f"$.cart.lines[{item.get('sku', item.get('id'))}]",
                            "item_id": item.get("id"),
                            "item_title": item.get("title"),
                            "message": msg,
                            "current": iqty,
                            "required_min": min_q,
                            "required_max": max_q,
                            "remediation": f"Increase '{item.get('title')}' by {shortfall} unit(s) (minimum {min_q}).",
                        }
                    )
                    rule_violated = True
                elif max_q is not None and iqty > max_q:
                    excess = iqty - max_q
                    msg = format_error_message(
                        template,
                        rtype,
                        {
                            "min": min_q if min_q else 1,
                            "max": max_q,
                            "current": iqty,
                            "excess": excess,
                            "item_title": item.get("title", "Item"),
                            "sku": item.get("sku", ""),
                        },
                    )
                    shopify_errors.append({"localizedMessage": msg, "target": "$.cart.lines"})
                    violations.append(
                        {
                            "rule_id": rule["rule_id"],
                            "rule_name": rule.get("name", "Per-Item Maximum"),
                            "rule_type": rtype,
                            "target": f"$.cart.lines[{item.get('sku', item.get('id'))}]",
                            "item_id": item.get("id"),
                            "item_title": item.get("title"),
                            "message": msg,
                            "current": iqty,
                            "required_min": min_q,
                            "required_max": max_q,
                            "remediation": f"Reduce '{item.get('title')}' to {max_q} unit(s) maximum.",
                        }
                    )
                    rule_violated = True

        # 4. Case Pack / Step Multiple Rule
        elif rtype == "step_multiple":
            step = int(step_val) if step_val is not None and int(step_val) > 1 else 1
            if step > 1:
                for item in active_items:
                    if not _item_matches_target(item, target_type, target_id):
                        continue
                    iqty = int(item.get("quantity", 0))
                    remainder = iqty % step
                    if remainder != 0:
                        shortfall = step - remainder
                        next_valid = iqty + shortfall
                        msg = format_error_message(
                            template,
                            rtype,
                            {
                                "step": step,
                                "current": iqty,
                                "shortfall": shortfall,
                                "item_title": item.get("title", "Item"),
                                "sku": item.get("sku", ""),
                            },
                        )
                        shopify_errors.append({"localizedMessage": msg, "target": "$.cart.lines"})
                        violations.append(
                            {
                                "rule_id": rule["rule_id"],
                                "rule_name": rule.get("name", "Case Pack Multiple"),
                                "rule_type": rtype,
                                "target": f"$.cart.lines[{item.get('sku', item.get('id'))}]",
                                "item_id": item.get("id"),
                                "item_title": item.get("title"),
                                "message": msg,
                                "current": iqty,
                                "required_step": step,
                                "remediation": f"Adjust '{item.get('title')}' to {next_valid} units (multiples of {step}).",
                            }
                        )
                        rule_violated = True

        # 5. Collection Aggregate Quantity Limit
        elif rtype == "collection_limit":
            min_q = int(min_val) if min_val is not None and float(min_val) > 0 else None
            max_q = int(max_val) if max_val is not None and float(max_val) > 0 else None
            matching_items = [
                i for i in active_items if _item_matches_target(i, "collection", target_id)
            ]
            col_qty = sum(int(i.get("quantity", 0)) for i in matching_items)
            # Only enforce collection minimums if at least 1 item from the collection is in the cart
            # (or if max is exceeded)
            if col_qty > 0 and min_q is not None and col_qty < min_q:
                shortfall = min_q - col_qty
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": min_q,
                        "max": max_q if max_q else "∞",
                        "current": col_qty,
                        "shortfall": shortfall,
                        "target_title": target_title,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Collection Limit"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": col_qty,
                        "required_min": min_q,
                        "required_max": max_q,
                        "remediation": f"Add {shortfall} more unit(s) from '{target_title}'.",
                    }
                )
                rule_violated = True
            elif max_q is not None and col_qty > max_q:
                excess = col_qty - max_q
                msg = format_error_message(
                    template,
                    rtype,
                    {
                        "min": min_q if min_q else 0,
                        "max": max_q,
                        "current": col_qty,
                        "excess": excess,
                        "target_title": target_title,
                    },
                )
                shopify_errors.append({"localizedMessage": msg, "target": "$.cart"})
                violations.append(
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule.get("name", "Collection Maximum"),
                        "rule_type": rtype,
                        "target": "$.cart",
                        "message": msg,
                        "current": col_qty,
                        "required_min": min_q,
                        "required_max": max_q,
                        "remediation": f"Remove {excess} unit(s) from '{target_title}' (max {max_q}).",
                    }
                )
                rule_violated = True

        if not rule_violated:
            passed_rules.append(
                {
                    "rule_id": rule["rule_id"],
                    "rule_name": rule.get("name", ""),
                    "rule_type": rtype,
                    "target_title": target_title,
                }
            )

    return {
        "valid": len(violations) == 0,
        "checkout_blocked": len(violations) > 0,
        "enforcement_enabled": True,
        "cart_subtotal": cart_subtotal,
        "cart_total_quantity": cart_total_qty,
        "errors": shopify_errors,
        "violations": violations,
        "passed_rules": passed_rules,
    }


def _item_matches_target(item: Dict[str, Any], target_type: str, target_id: str) -> bool:
    if target_type == "all" or target_id == "all":
        return True
    if target_type == "product":
        return (
            str(item.get("id")) == target_id
            or str(item.get("sku", "")).lower() == target_id.lower()
        )
    if target_type == "collection":
        cols = item.get("collections") or []
        return target_id in cols or str(item.get("collection_id", "")) == target_id
    return True


def compile_shopify_function_config(
    shop_domain: str,
    rules: List[Dict[str, Any]],
    enforcement_enabled: bool = True,
) -> Dict[str, Any]:
    """
    Compile rules into a compact JSON schema suitable for Shopify Metafield
    `$app:cart_validation_rules` consumed by a Shopify Cart & Checkout Validation Function.
    """
    active = [r for r in rules if r.get("is_active", True)]
    compiled_rules = []
    for r in sorted(active, key=lambda x: int(x.get("priority", 10))):
        compiled_rules.append(
            {
                "id": r["rule_id"],
                "t": r["rule_type"],
                "scope": r["target_type"],
                "tid": r["target_id"],
                "seg": r.get("customer_segment", "all"),
                "tag": r.get("customer_tag", ""),
                "min": r.get("min_val"),
                "max": r.get("max_val"),
                "step": r.get("step_val"),
                "msg": r.get("error_template") or DEFAULT_ERROR_TEMPLATES.get(r["rule_type"], ""),
            }
        )
    return {
        "schema": "shopify.functions.cart-checkout-validation.v1",
        "shop": shop_domain,
        "enabled": enforcement_enabled,
        "active_rules_count": len(compiled_rules),
        "rules": compiled_rules,
    }

