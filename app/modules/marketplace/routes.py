from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.deps import ApiContext, project_scope, scope_guard
from app.modules.marketplace.schema import (
    CategoryCreate,
    CouponCreate,
    CustomerCreate,
    OrderCreate,
    OrderStatusUpdate,
    ProductCreate,
    ProductUpdate,
    SellerCreate,
    StoreCreate,
)
from app.modules.marketplace.service import MarketplaceService
from app.modules.payments.schema import PaymentMethod

router = APIRouter(tags=["Marketplace"])
service = MarketplaceService()

read_guard = scope_guard("marketplace:read", "marketplace")
write_guard = scope_guard("marketplace:write", "marketplace")


class CheckoutRequest(BaseModel):
    payment_method: PaymentMethod = PaymentMethod()


# ---------- Public API (API key) ----------

@router.get("/v1/stores")
async def api_list_stores(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_stores(ctx.project_id, limit, skip)}


@router.post("/v1/stores")
async def api_create_store(payload: StoreCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_store(ctx.project_id, payload)


@router.get("/v1/products")
async def api_list_products(limit: int = 50, skip: int = 0, search: str | None = None,
                            ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_products(ctx.project_id, limit, skip, search)}


@router.post("/v1/products")
async def api_create_product(payload: ProductCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_product(ctx.project_id, payload)


@router.get("/v1/orders")
async def api_list_orders(limit: int = 50, skip: int = 0, status: str | None = None,
                          ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_orders(ctx.project_id, limit, skip, status)}


@router.post("/v1/orders")
async def api_create_order(payload: OrderCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_order(ctx.project_id, payload)


@router.post("/v1/orders/{order_id}/checkout")
async def api_checkout(order_id: str, payload: CheckoutRequest, ctx: ApiContext = Depends(write_guard)):
    return await service.checkout_order(ctx.project_id, ctx.project["organization_id"], order_id,
                                        payload.payment_method.model_dump())


@router.get("/v1/customers")
async def api_list_customers(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_customers(ctx.project_id, limit, skip)}


@router.post("/v1/customers")
async def api_create_customer(payload: CustomerCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_customer(ctx.project_id, payload)


@router.get("/v1/sellers")
async def api_list_sellers(limit: int = 50, skip: int = 0, ctx: ApiContext = Depends(read_guard)):
    return {"data": await service.list_sellers(ctx.project_id, limit, skip)}


@router.post("/v1/sellers")
async def api_create_seller(payload: SellerCreate, ctx: ApiContext = Depends(write_guard)):
    return await service.create_seller(ctx.project_id, payload)


# ---------- Dashboard (JWT) ----------

@router.get("/dashboard/marketplace/overview")
async def overview(project_id: str, project: dict = Depends(project_scope)):
    return {
        "stores": await service.list_stores(project_id),
        "sellers": await service.list_sellers(project_id),
        "categories": await service.list_categories(project_id),
        "coupons": await service.list_coupons(project_id),
    }


@router.post("/dashboard/marketplace/stores")
async def create_store(project_id: str, payload: StoreCreate, project: dict = Depends(project_scope)):
    return await service.create_store(project_id, payload)


@router.post("/dashboard/marketplace/sellers")
async def create_seller(project_id: str, payload: SellerCreate, project: dict = Depends(project_scope)):
    return await service.create_seller(project_id, payload)


@router.post("/dashboard/marketplace/categories")
async def create_category(project_id: str, payload: CategoryCreate, project: dict = Depends(project_scope)):
    return await service.create_category(project_id, payload.name, payload.description)


@router.post("/dashboard/marketplace/coupons")
async def create_coupon(project_id: str, payload: CouponCreate, project: dict = Depends(project_scope)):
    return await service.create_coupon(project_id, payload)


@router.get("/dashboard/products")
async def list_products(project_id: str, limit: int = 50, skip: int = 0, search: str | None = None,
                        project: dict = Depends(project_scope)):
    return {"data": await service.list_products(project_id, limit, skip, search)}


@router.post("/dashboard/products")
async def create_product(project_id: str, payload: ProductCreate, project: dict = Depends(project_scope)):
    return await service.create_product(project_id, payload)


@router.patch("/dashboard/products/{product_id}")
async def update_product(project_id: str, product_id: str, payload: ProductUpdate,
                         project: dict = Depends(project_scope)):
    return await service.update_product(project_id, product_id, payload.model_dump(exclude_none=True))


@router.delete("/dashboard/products/{product_id}")
async def delete_product(project_id: str, product_id: str, project: dict = Depends(project_scope)):
    return await service.delete_product(project_id, product_id)


@router.get("/dashboard/orders")
async def list_orders(project_id: str, limit: int = 50, skip: int = 0, status: str | None = None,
                      project: dict = Depends(project_scope)):
    return {"data": await service.list_orders(project_id, limit, skip, status)}


@router.post("/dashboard/orders")
async def create_order(project_id: str, payload: OrderCreate, project: dict = Depends(project_scope)):
    return await service.create_order(project_id, payload)


@router.patch("/dashboard/orders/{order_id}")
async def update_order(project_id: str, order_id: str, payload: OrderStatusUpdate,
                       project: dict = Depends(project_scope)):
    return await service.update_order_status(project_id, order_id, payload.status)


@router.post("/dashboard/orders/{order_id}/checkout")
async def checkout(project_id: str, order_id: str, payload: CheckoutRequest,
                   project: dict = Depends(project_scope)):
    return await service.checkout_order(project_id, project["organization_id"], order_id, payload.payment_method.model_dump())


@router.get("/dashboard/customers")
async def list_customers(project_id: str, limit: int = 50, skip: int = 0, project: dict = Depends(project_scope)):
    return {"data": await service.list_customers(project_id, limit, skip)}


@router.post("/dashboard/customers")
async def create_customer(project_id: str, payload: CustomerCreate, project: dict = Depends(project_scope)):
    return await service.create_customer(project_id, payload)


@router.get("/dashboard/sellers")
async def list_sellers(project_id: str, limit: int = 50, skip: int = 0, project: dict = Depends(project_scope)):
    return {"data": await service.list_sellers(project_id, limit, skip)}
