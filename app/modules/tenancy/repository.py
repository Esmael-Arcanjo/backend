from app.core.repository import BaseRepository


class OrganizationRepository(BaseRepository):
    collection_name = "organizations"


class ProjectRepository(BaseRepository):
    collection_name = "projects"


class ApiKeyRepository(BaseRepository):
    collection_name = "api_keys"
