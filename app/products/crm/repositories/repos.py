from app.shared.repository import TenantRepository
from app.products.crm.models.documents import Activity, Contact, Lead, Opportunity, Pipeline

leads = TenantRepository("crm_leads", Lead)
contacts = TenantRepository("crm_contacts", Contact)
opportunities = TenantRepository("crm_opportunities", Opportunity)
activities = TenantRepository("crm_activities", Activity)
pipelines = TenantRepository("crm_pipelines", Pipeline)
