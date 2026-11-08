"""
Shopify Admin GraphQL API Client (2025-01) for CartLogic — Order & Quantity Limits.
Supports catalog querying, metafield rule synchronization, and Shopify Billing API.
"""
import json
from typing import Any, Dict, List
import httpx

SHOPIFY_API_VERSION = "2025-01"


class ShopifyGraphQLClient:
    def __init__(self, shop_domain: str, access_token: str) -> None:
        self.shop_domain = shop_domain.strip().lower()
        self.access_token = access_token.strip()
        self.endpoint = (
            f"https://{self.shop_domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        )

    async def execute(
        self, query: str, variables: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
            if "errors" in body and body["errors"]:
                raise RuntimeError(f"Shopify GraphQL error: {body['errors']}")
            return body.get("data", {})

    async def fetch_catalog_targets(self, limit: int = 25) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch live collections and products from the merchant's store."""
        query = """
        query FetchCatalog($limit: Int!) {
          collections(first: $limit) {
            edges {
              node {
                id
                title
                handle
                productsCount {
                  count
                }
              }
            }
          }
          products(first: $limit) {
            edges {
              node {
                id
                title
                handle
                variants(first: 1) {
                  edges {
                    node {
                      id
                      sku
                      price
                      inventoryQuantity
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = await self.execute(query, {"limit": limit})
        collections = []
        for edge in data.get("collections", {}).get("edges", []):
            node = edge["node"]
            collections.append(
                {
                    "id": node["id"],
                    "title": node["title"],
                    "handle": node.get("handle", ""),
                    "products_count": (node.get("productsCount") or {}).get("count", 0),
                }
            )

        products = []
        for edge in data.get("products", {}).get("edges", []):
            node = edge["node"]
            v_edges = (node.get("variants") or {}).get("edges", [])
            v_node = v_edges[0]["node"] if v_edges else {}
            products.append(
                {
                    "id": node["id"],
                    "title": node["title"],
                    "sku": v_node.get("sku") or node.get("handle", "").upper()[:10],
                    "price": float(v_node.get("price") or 0.0),
                    "inventory": int(v_node.get("inventoryQuantity") or 0),
                    "collections": [c["id"] for c in collections[:1]],
                }
            )
        return {"collections": collections, "products": products}

    async def sync_validation_metafield(self, compiled_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query shop GID and persist the compiled validation rules JSON into the Shop Metafield
        so Shopify Cart & Checkout Validation Functions can enforce rules at the edge.
        """
        shop_q = "query { shop { id name } }"
        shop_data = await self.execute(shop_q)
        shop_id = (shop_data.get("shop") or {}).get("id")
        if not shop_id:
            raise RuntimeError("Unable to resolve Shop GID for metafield sync")

        mutation = """
        mutation MetafieldsSet($metafields: [MetafieldsSetInput!]!) {
          metafieldsSet(metafields: $metafields) {
            metafields {
              id
              namespace
              key
              updatedAt
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        variables = {
            "metafields": [
                {
                    "ownerId": shop_id,
                    "namespace": "cartlogic",
                    "key": "validation_rules_v1",
                    "type": "json",
                    "value": json.dumps(compiled_config),
                }
            ]
        }
        return await self.execute(mutation, variables)

    async def create_subscription(
        self,
        return_url: str,
        plan_name: str = "Pro Validation",
        price_usd: float = 9.99,
        trial_days: int = 14,
        test_mode: bool = True,
    ) -> Dict[str, Any]:
        mutation = """
        mutation AppSubscriptionCreate(
          $name: String!,
          $returnUrl: URL!,
          $trialDays: Int!,
          $test: Boolean!,
          $amount: Decimal!
        ) {
          appSubscriptionCreate(
            name: $name,
            returnUrl: $returnUrl,
            trialDays: $trialDays,
            test: $test,
            lineItems: [
              {
                plan: {
                  appRecurringPricingDetails: {
                    price: { amount: $amount, currencyCode: USD },
                    interval: EVERY_30_DAYS
                  }
                }
              }
            ]
          ) {
            confirmationUrl
            appSubscription {
              id
              status
            }
            userErrors {
              field
              message
            }
          }
        }
        """
        return await self.execute(
            mutation,
            {
                "name": plan_name,
                "returnUrl": return_url,
                "trialDays": trial_days,
                "test": test_mode,
                "amount": str(price_usd),
            },
        )

