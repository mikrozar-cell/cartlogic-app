"""
SQLite Persistence Layer for CartLogic — Order & Quantity Limits.
Stores shops, validation rules, checkout block events, and audit logs.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "CARTLIMITS_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "cartlimits.sqlite3"),
)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shops (
                shop_domain TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                scope TEXT NOT NULL,
                plan_name TEXT DEFAULT 'free',
                enforcement_enabled INTEGER DEFAULT 1,
                installed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS validation_rules (
                rule_id TEXT NOT NULL,
                shop_domain TEXT NOT NULL,
                name TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_title TEXT NOT NULL,
                customer_segment TEXT NOT NULL DEFAULT 'all',
                customer_tag TEXT DEFAULT '',
                min_val REAL,
                max_val REAL,
                step_val INTEGER,
                error_template TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 10,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (shop_domain, rule_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_domain TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def upsert_shop(shop_domain: str, access_token: str, scope: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shops (shop_domain, access_token, scope, installed_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(shop_domain) DO UPDATE SET
                access_token = excluded.access_token,
                scope = excluded.scope,
                updated_at = excluded.updated_at
            """,
            (shop_domain.lower().strip(), access_token, scope, now, now),
        )
        conn.commit()


def get_shop(shop_domain: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM shops WHERE shop_domain = ?",
            (shop_domain.lower().strip(),),
        ).fetchone()
        return dict(row) if row else None


def set_shop_enforcement(shop_domain: str, enabled: bool) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shops (shop_domain, access_token, scope, enforcement_enabled, installed_at, updated_at)
            VALUES (?, '', '', ?, ?, ?)
            ON CONFLICT(shop_domain) DO UPDATE SET
                enforcement_enabled = excluded.enforcement_enabled,
                updated_at = excluded.updated_at
            """,
            (shop_domain.lower().strip(), 1 if enabled else 0, now, now),
        )
        conn.commit()


def get_shop_enforcement(shop_domain: str) -> bool:
    shop = get_shop(shop_domain)
    if not shop:
        return True
    return bool(shop.get("enforcement_enabled", 1))


def list_rules(shop_domain: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM validation_rules
            WHERE shop_domain = ?
            ORDER BY priority ASC, updated_at DESC
            """,
            (shop_domain.lower().strip(),),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["is_active"] = bool(d["is_active"])
            result.append(d)
        return result


def save_rule(shop_domain: str, rule: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    clean_shop = shop_domain.lower().strip()
    rule_id = str(rule["rule_id"]).strip()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO validation_rules (
                rule_id, shop_domain, name, rule_type, target_type, target_id,
                target_title, customer_segment, customer_tag, min_val, max_val,
                step_val, error_template, is_active, priority, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(shop_domain, rule_id) DO UPDATE SET
                name = excluded.name,
                rule_type = excluded.rule_type,
                target_type = excluded.target_type,
                target_id = excluded.target_id,
                target_title = excluded.target_title,
                customer_segment = excluded.customer_segment,
                customer_tag = excluded.customer_tag,
                min_val = excluded.min_val,
                max_val = excluded.max_val,
                step_val = excluded.step_val,
                error_template = excluded.error_template,
                is_active = excluded.is_active,
                priority = excluded.priority,
                updated_at = excluded.updated_at
            """,
            (
                rule_id,
                clean_shop,
                rule.get("name", "Untitled Rule"),
                rule.get("rule_type", "item_quantity"),
                rule.get("target_type", "all"),
                rule.get("target_id", "all"),
                rule.get("target_title", "Entire Catalog"),
                rule.get("customer_segment", "all"),
                rule.get("customer_tag", ""),
                rule.get("min_val"),
                rule.get("max_val"),
                rule.get("step_val"),
                rule.get("error_template", ""),
                1 if rule.get("is_active", True) else 0,
                int(rule.get("priority", 10)),
                now,
            ),
        )
        conn.commit()
    return {**rule, "shop_domain": clean_shop, "updated_at": now, "is_active": bool(rule.get("is_active", True))}


def delete_rule(shop_domain: str, rule_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM validation_rules WHERE shop_domain = ? AND rule_id = ?",
            (shop_domain.lower().strip(), rule_id.strip()),
        )
        conn.commit()
        return cur.rowcount > 0


def add_audit_log(shop_domain: str, action: str, details: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (shop_domain, action, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (shop_domain.lower().strip(), action, json.dumps(details), now),
        )
        conn.commit()


def get_audit_logs(shop_domain: str, limit: int = 25) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, action, details, created_at
            FROM audit_logs
            WHERE shop_domain = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (shop_domain.lower().strip(), limit),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "action": r["action"],
                    "details": json.loads(r["details"]),
                    "created_at": r["created_at"],
                }
            )
        return out


def delete_shop_data(shop_domain: str) -> None:
    clean = shop_domain.lower().strip()
    with get_connection() as conn:
        conn.execute("DELETE FROM validation_rules WHERE shop_domain = ?", (clean,))
        conn.execute("DELETE FROM audit_logs WHERE shop_domain = ?", (clean,))
        conn.execute("DELETE FROM shops WHERE shop_domain = ?", (clean,))
        conn.commit()


init_db()

