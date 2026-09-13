from app.core.repository import BaseRepository


class StoreRepository(BaseRepository):
    collection_name = "stores"


class SellerRepository(BaseRepository):
    collection_name = "sellers"


class CustomerRepository(BaseRepository):
    collection_name = "customers"


class CategoryRepository(BaseRepository):
    collection_name = "categories"


class ProductRepository(BaseRepository):
    collection_name = "products"


class InventoryRepository(BaseRepository):
    collection_name = "inventory"


class OrderRepository(BaseRepository):
    collection_name = "orders"


class CouponRepository(BaseRepository):
    collection_name = "coupons"
