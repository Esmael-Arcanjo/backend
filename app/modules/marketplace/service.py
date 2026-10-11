import re

from fastapi import HTTPException

from app.core.mongo import oid
from app.modules.marketplace.repository import (
    CategoryRepository,
    CouponRepository,
    CustomerRepository,
    InventoryRepository,
    OrderRepository,
    ProductRepository,
    SellerRepository,
    StoreRepository,
)
from app.modules.marketplace.schema import (
    CouponCreate,
    CustomerCreate,
    OrderCreate,
    ProductCreate,
    SellerCreate,
    StoreCreate,
)
from app.modules.webhooks.service import WebhookService


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class MarketplaceService:
    def __init__(self) -> None:
        self.stores = StoreRepository()
        self.sellers = SellerRepository()
        self.customers = CustomerRepository()
        self.categories = CategoryRepository()
        self.products = ProductRepository()
        self.inventory = InventoryRepository()
        self.orders = OrderRepository()
        self.coupons = CouponRepository()
        self.webhooks = WebhookService()

    @staticmethod
    def _new(doc: dict) -> dict:
        doc["id"] = doc.pop("_id")
        return doc

    # ---------- stores ----------
    async def create_store(self, project_id: str, payload: StoreCreate) -> dict:
        return self._new(await self.stores.insert({
            "project_id": project_id, "name": payload.name, "slug": slugify(payload.name),
            "currency": payload.currency.upper(), "commission_bps": payload.commission_bps, "status": "active"}))

    async def list_stores(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.stores.find_many({"project_id": project_id}, limit=limit, skip=skip)

    # ---------- sellers ----------
    async def create_seller(self, project_id: str, payload: SellerCreate) -> dict:
        return self._new(await self.sellers.insert({
            "project_id": project_id, "store_id": payload.store_id, "name": payload.name,
            "email": payload.email.lower(), "commission_bps": payload.commission_bps, "status": "active"}))

    async def list_sellers(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.sellers.find_many({"project_id": project_id}, limit=limit, skip=skip)

    # ---------- customers ----------
    async def create_customer(self, project_id: str, payload: CustomerCreate) -> dict:
        return self._new(await self.customers.insert({
            "project_id": project_id, "name": payload.name, "email": payload.email.lower(),
            "phone": payload.phone, "country": payload.country, "metadata": {}}))

    async def list_customers(self, project_id: str, limit: int = 50, skip: int = 0) -> list[dict]:
        return await self.customers.find_many({"project_id": project_id}, limit=limit, skip=skip)

    # ---------- categories ----------
    async def create_category(self, project_id: str, name: str, description: str = "") -> dict:
        return self._new(await self.categories.insert({
            "project_id": project_id, "name": name, "slug": slugify(name), "description": description}))

    async def list_categories(self, project_id: str) -> list[dict]:
        return await self.categories.find_many({"project_id": project_id}, limit=200)

    # ---------- products ----------
    async def create_product(self, project_id: str, payload: ProductCreate) -> dict:
        product = self._new(await self.products.insert({
            "project_id": project_id, "store_id": payload.store_id, "seller_id": payload.seller_id,
            "category_id": payload.category_id, "name": payload.name, "sku": payload.sku,
            "price": payload.price, "currency": payload.currency.upper(), "stock": payload.stock,
            "active": True, "description": payload.description, "image_url": payload.image_url}))
        await self.inventory.insert({"project_id": project_id, "product_id": product["id"],
                                     "quantity": payload.stock, "reserved": 0})
        return product

    async def list_products(self, project_id: str, limit: int = 50, skip: int = 0, search: str | None = None) -> list[dict]:
        query: dict = {"project_id": project_id}
        if search:
            query["name"] = {"$regex": re.escape(search), "$options": "i"}
        return await self.products.find_many(query, limit=limit, skip=skip)

    async def update_product(self, project_id: str, product_id: str, changes: dict) -> dict:
        product = await self.products.update(product_id, changes, extra={"project_id": project_id})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        if "stock" in changes:
            await self.inventory.collection.update_one({"product_id": product_id},
                                                       {"$set": {"quantity": changes["stock"]}}, upsert=True)
        return product

    async def delete_product(self, project_id: str, product_id: str) -> dict:
        await self.products.delete(product_id, extra={"project_id": project_id})
        return {"status": "deleted"}

    # ---------- coupons ----------
    async def create_coupon(self, project_id: str, payload: CouponCreate) -> dict:
        return self._new(await self.coupons.insert({
            "project_id": project_id, "code": payload.code.upper(), "type": payload.type,
            "value": payload.value, "max_redemptions": payload.max_redemptions,
            "redemptions": 0, "active": payload.active}))

    async def list_coupons(self, project_id: str) -> list[dict]:
        return await self.coupons.find_many({"project_id": project_id}, limit=100)

    # ---------- orders ----------
    async def create_order(self, project_id: str, payload: OrderCreate) -> dict:
        items = []
        subtotal = 0
        commissions: dict[str, int] = {}
        for item in payload.items:
            product = await self.products.get(item.product_id, extra={"project_id": project_id})
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
            if product.get("stock", 0) < item.quantity:
                raise HTTPException(status_code=422, detail=f"Insufficient stock for {product['name']}")
            line_total = product["price"] * item.quantity
            subtotal += line_total
            items.append({"product_id": product["id"], "name": product["name"], "sku": product["sku"],
                          "unit_price": product["price"], "quantity": item.quantity, "total": line_total,
                          "seller_id": product.get("seller_id")})
            if product.get("seller_id"):
                commissions[product["seller_id"]] = commissions.get(product["seller_id"], 0) + line_total

        discount = 0
        coupon = None
        if payload.coupon_code:
            coupon = await self.coupons.find_one({"project_id": project_id, "code": payload.coupon_code.upper(),
                                                  "active": True})
            if not coupon:
                raise HTTPException(status_code=404, detail="Coupon not found")
            if coupon.get("redemptions", 0) >= coupon.get("max_redemptions", 0):
                raise HTTPException(status_code=422, detail="Coupon exhausted")
            discount = (subtotal * coupon["value"]) // 100 if coupon["type"] == "percent" else min(coupon["value"], subtotal)

        total = subtotal - discount
        splits = []
        if commissions and total > 0:
            for seller_id, seller_gross in commissions.items():
                seller = await self.sellers.get(seller_id)
                commission_bps = (seller or {}).get("commission_bps", 1000)
                seller_bps = (seller_gross * 10000) // subtotal
                payout_bps = (seller_bps * (10000 - commission_bps)) // 10000
                splits.append({"destination": seller_id, "bps": payout_bps})

        order = self._new(await self.orders.insert({
            "project_id": project_id, "store_id": payload.store_id, "customer_id": payload.customer_id,
            "items": items, "subtotal": subtotal, "discount": discount, "total": total,
            "currency": payload.currency.upper(), "status": "pending",
            "coupon_code": payload.coupon_code, "splits": splits}))

        for item in items:
            await self.products.collection.update_one({"_id": oid(item["product_id"])},
                                                      {"$inc": {"stock": -item["quantity"]}})
            await self.inventory.collection.update_one({"product_id": item["product_id"]},
                                                       {"$inc": {"quantity": -item["quantity"]}})
        if coupon:
            await self.coupons.collection.update_one({"_id": oid(coupon["id"])},
                                                     {"$inc": {"redemptions": 1}})
        await self.webhooks.dispatch(project_id, "order.created",
                                     {"order_id": order["id"], "total": total, "currency": order["currency"]})
        return order

    async def list_orders(self, project_id: str, limit: int = 50, skip: int = 0, status: str | None = None) -> list[dict]:
        query: dict = {"project_id": project_id}
        if status:
            query["status"] = status
        return await self.orders.find_many(query, limit=limit, skip=skip)

    async def get_order(self, project_id: str, order_id: str) -> dict:
        order = await self.orders.get(order_id, extra={"project_id": project_id})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    async def update_order_status(self, project_id: str, order_id: str, status: str) -> dict:
        order = await self.orders.update(order_id, {"status": status}, extra={"project_id": project_id})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    async def checkout_order(self, project_id: str, organization_id: str, order_id: str,
                             payment_method: dict) -> dict:
        """Pay an order with LEAMSE Payments, applying the seller split automatically."""
        from app.modules.payments.schema import PaymentIntentCreate, PaymentMethod
        from app.modules.payments.service import PaymentService

        order = await self.get_order(project_id, order_id)
        if order["status"] != "pending":
            raise HTTPException(status_code=409, detail="Order is not pending")
        payments = PaymentService()
        intent = await payments.create_intent(project_id, PaymentIntentCreate(
            amount=order["total"], currency=order["currency"], description=f"Order {order_id}",
            customer_id=order.get("customer_id"), order_id=order_id,
            splits=order.get("splits", [])))
        charge = await payments.create_charge(project_id, organization_id, intent["id"],
                                             PaymentMethod(**payment_method))
        if charge["status"] in ("captured",):
            await self.orders.update(order_id, {"status": "paid", "payment_intent_id": intent["id"]})
        return {"order_id": order_id, "payment_intent": intent, "charge": charge}
