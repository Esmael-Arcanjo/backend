"""Idempotent Stripe catalog sync for purchasable plans (lookup_key = <product>_<plan>_monthly)."""
import os
import sys

import stripe
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.core.products_catalog.catalog_data import PLANS, PRODUCTS, lookup_key  # noqa: E402

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]


def get_or_create_product(key: str, name: str):
    for p in stripe.Product.list(active=True).auto_paging_iter():
        if p.to_dict().get("metadata", {}).get("emergent_product_id") == key:
            return p
    return stripe.Product.create(name=name, tax_code="txcd_10103001",
                                 metadata={"managed_by": "emergent", "emergent_product_id": key})


def main():
    names = {p["key"]: p["name"] for p in PRODUCTS if p["status"] == "available"}
    for plan in PLANS:
        if plan["product_key"] not in names:
            continue
        product = get_or_create_product(f"{plan['product_key']}_{plan['plan_key']}",
                                        f"{names[plan['product_key']]} — {plan['name']}")
        lk = lookup_key(plan["product_key"], plan["plan_key"], plan["interval"])
        existing = stripe.Price.list(lookup_keys=[lk], active=True, limit=1).data
        if existing and (existing[0].unit_amount != plan["price_cents"] or existing[0].currency != plan["currency"]):
            stripe.Price.modify(existing[0].id, active=False)
            existing = []
        if not existing:
            stripe.Price.create(product=product.id, unit_amount=plan["price_cents"], currency=plan["currency"],
                                lookup_key=lk, transfer_lookup_key=True, recurring={"interval": plan["interval"]})
        print("ok", lk)


if __name__ == "__main__":
    main()
