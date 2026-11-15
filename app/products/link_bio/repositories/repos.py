from app.shared.repository import TenantRepository
from app.products.link_bio.models.documents import BioLink, BioPage, BioTheme

pages = TenantRepository("bio_pages", BioPage)
links = TenantRepository("bio_links", BioLink)
themes = TenantRepository("bio_themes", BioTheme)
