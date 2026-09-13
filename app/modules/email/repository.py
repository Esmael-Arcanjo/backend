from app.core.repository import BaseRepository


class EmailTemplateRepository(BaseRepository):
    collection_name = "email_templates"


class EmailLogRepository(BaseRepository):
    collection_name = "email_logs"
