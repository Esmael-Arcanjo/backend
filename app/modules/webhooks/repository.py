from app.core.repository import BaseRepository


class WebhookRepository(BaseRepository):
    collection_name = "webhooks"


class WebhookDeliveryRepository(BaseRepository):
    collection_name = "webhook_deliveries"
