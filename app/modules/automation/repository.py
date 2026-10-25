from app.core.repository import BaseRepository


class AppointmentRepository(BaseRepository):
    collection_name = "appointments"


class ContactRepository(BaseRepository):
    collection_name = "crm_contacts"


class FlowRepository(BaseRepository):
    collection_name = "automation_flows"


class WaMessageRepository(BaseRepository):
    collection_name = "wa_messages"
