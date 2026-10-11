from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.mongo import BaseDocument


class Store(BaseDocument):
    project_id: str
    name: str
    slug: str
    currency: str = "BRL"
    commission_bps: int = 1000
    status: Literal["active", "paused"] = "active"


class Seller(BaseDocument):
    project_id: str
    store_id: Optional[str] = None
    name: str
    email: str
    commission_bps: int = 1000
    status: Literal["active", "suspended"] = "active"


class Customer(BaseDocument):
    project_id: str
    name: str
    email: str
    phone: str = ""
    country: str = "BR"
    metadata: dict = Field(default_factory=dict)


class Product(BaseDocument):
    project_id: str
    store_id: Optional[str] = None
    seller_id: Optional[str] = None
    category_id: Optional[str] = None
    name: str
    sku: str
    price: int
    currency: str = "BRL"
    stock: int = 0
    active: bool = True
    description: str = ""
    image_url: str = ""


class Order(BaseDocument):
    project_id: str
    store_id: Optional[str] = None
    customer_id: Optional[str] = None
    items: list[dict] = Field(default_factory=list)
    subtotal: int = 0
    discount: int = 0
    total: int = 0
    currency: str = "BRL"
    status: Literal["pending", "paid", "shipped", "delivered", "canceled", "refunded"] = "pending"
    coupon_code: Optional[str] = None
    splits: list[dict] = Field(default_factory=list)
    payment_intent_id: Optional[str] = None


# ---------- request schemas ----------

class StoreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    currency: str = "BRL"
    commission_bps: int = Field(default=1000, ge=0, le=10000)


class SellerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    store_id: Optional[str] = None
    commission_bps: int = Field(default=1000, ge=0, le=10000)


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    phone: str = ""
    country: str = "BR"


class CategoryCreate(BaseModel):
    name: str
    description: str = ""


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    sku: str
    price: int = Field(gt=0)
    currency: str = "BRL"
    stock: int = 0
    store_id: Optional[str] = None
    seller_id: Optional[str] = None
    category_id: Optional[str] = None
    description: str = ""
    image_url: str = ""


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[int] = Field(default=None, gt=0)
    stock: Optional[int] = None
    active: Optional[bool] = None
    description: Optional[str] = None
    image_url: Optional[str] = None


class OrderItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    customer_id: Optional[str] = None
    store_id: Optional[str] = None
    items: list[OrderItem]
    coupon_code: Optional[str] = None
    currency: str = "BRL"


class OrderStatusUpdate(BaseModel):
    status: Literal["pending", "paid", "shipped", "delivered", "canceled", "refunded"]


class CouponCreate(BaseModel):
    code: str
    type: Literal["percent", "fixed"] = "percent"
    value: int = Field(gt=0)
    max_redemptions: int = 100
    active: bool = True
