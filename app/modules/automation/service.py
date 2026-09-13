import os

from fastapi import HTTPException

from app.modules.automation.repository import (
    AppointmentRepository,
    ContactRepository,
    FlowRepository,
    WaMessageRepository,
)
from app.modules.automation.schema import STAGES

ASSISTANT_SYSTEM = (
    "Você é o Assistente WhatsApp da LEAMSE Automação, atendendo clientes de um negócio em nome do dono. "
    "Responda sempre em português, de forma cordial, curta e objetiva, como em uma conversa de WhatsApp. "
    "Seu objetivo é: (1) responder dúvidas, (2) ajudar a agendar horários perguntando nome, serviço desejado "
    "e melhor dia/horário, e (3) qualificar leads. Nunca invente preços ou informações que não foram fornecidas. "
    "Quando o cliente quiser agendar, confirme os dados coletados ao final."
)


class AutomationService:
    def __init__(self) -> None:
        self.appointments = AppointmentRepository()
        self.contacts = ContactRepository()
        self.flows = FlowRepository()
        self.messages = WaMessageRepository()

    # ---------- Agenda ----------
    async def list_appointments(self, project_id: str, limit: int = 200, skip: int = 0) -> list[dict]:
        return await self.appointments.find_many(
            {"project_id": project_id}, limit=limit, skip=skip, sort_field="scheduled_at"
        )

    async def create_appointment(self, project_id: str, payload) -> dict:
        doc = await self.appointments.insert(
            {**payload.model_dump(), "project_id": project_id, "status": "scheduled", "reminder_sent": False}
        )
        doc["id"] = doc.pop("_id")
        return doc

    async def update_appointment(self, project_id: str, appointment_id: str, changes: dict) -> dict:
        appt = await self.appointments.update(appointment_id, changes, extra={"project_id": project_id})
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")
        return appt

    async def delete_appointment(self, project_id: str, appointment_id: str) -> dict:
        await self.appointments.delete(appointment_id, extra={"project_id": project_id})
        return {"status": "deleted"}

    # ---------- CRM ----------
    async def list_contacts(self, project_id: str, limit: int = 500, skip: int = 0) -> list[dict]:
        return await self.contacts.find_many({"project_id": project_id}, limit=limit, skip=skip)

    async def create_contact(self, project_id: str, payload) -> dict:
        data = payload.model_dump()
        if data.get("stage") not in STAGES:
            data["stage"] = "lead"
        doc = await self.contacts.insert({**data, "project_id": project_id})
        doc["id"] = doc.pop("_id")
        return doc

    async def update_contact(self, project_id: str, contact_id: str, changes: dict) -> dict:
        if "stage" in changes and changes["stage"] not in STAGES:
            raise HTTPException(status_code=400, detail="Invalid stage")
        contact = await self.contacts.update(contact_id, changes, extra={"project_id": project_id})
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        return contact

    async def delete_contact(self, project_id: str, contact_id: str) -> dict:
        await self.contacts.delete(contact_id, extra={"project_id": project_id})
        return {"status": "deleted"}

    # ---------- Flows ----------
    async def list_flows(self, project_id: str) -> list[dict]:
        return await self.flows.find_many({"project_id": project_id}, limit=200)

    async def create_flow(self, project_id: str, payload) -> dict:
        doc = await self.flows.insert({**payload.model_dump(), "project_id": project_id, "runs": 0})
        doc["id"] = doc.pop("_id")
        return doc

    async def update_flow(self, project_id: str, flow_id: str, changes: dict) -> dict:
        flow = await self.flows.update(flow_id, changes, extra={"project_id": project_id})
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        return flow

    async def delete_flow(self, project_id: str, flow_id: str) -> dict:
        await self.flows.delete(flow_id, extra={"project_id": project_id})
        return {"status": "deleted"}

    # ---------- Overview ----------
    async def overview(self, project_id: str) -> dict:
        appts = await self.appointments.find_many({"project_id": project_id}, limit=1000, sort_field="scheduled_at")
        contacts = await self.contacts.find_many({"project_id": project_id}, limit=1000)
        flows = await self.flows.find_many({"project_id": project_id}, limit=200)
        pipeline = {s: 0 for s in STAGES}
        for c in contacts:
            stage = c.get("stage", "lead")
            pipeline[stage] = pipeline.get(stage, 0) + 1
        won_value = sum(c.get("value", 0) or 0 for c in contacts if c.get("stage") == "won")
        upcoming = [a for a in appts if a.get("status") in ("scheduled", "confirmed")]
        return {
            "appointments_total": len(appts),
            "appointments_upcoming": len(upcoming),
            "contacts_total": len(contacts),
            "won_value": won_value,
            "flows_active": len([f for f in flows if f.get("active")]),
            "flows_total": len(flows),
            "pipeline": pipeline,
            "stages": STAGES,
            "recent_appointments": upcoming[:6],
            "recent_contacts": contacts[:6],
        }

    # ---------- WhatsApp AI Assistant ----------
    async def list_messages(self, project_id: str, session_id: str, limit: int = 100) -> list[dict]:
        msgs = await self.messages.find_many(
            {"project_id": project_id, "session_id": session_id}, limit=limit
        )
        return list(reversed(msgs))

    async def chat(self, project_id: str, session_id: str, message: str) -> dict:
        from emergentintegrations.llm.chat import LlmChat, UserMessage

        key = os.environ.get("EMERGENT_LLM_KEY")
        if not key:
            raise HTTPException(status_code=500, detail="LLM key not configured")

        await self.messages.insert(
            {"project_id": project_id, "session_id": session_id, "role": "user", "content": message}
        )
        history = await self.messages.find_many(
            {"project_id": project_id, "session_id": session_id}, limit=12
        )
        history = list(reversed(history))
        transcript = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in history[-10:])
        system = f"{ASSISTANT_SYSTEM}\n\nHistórico recente da conversa:\n{transcript}"

        chat = LlmChat(
            api_key=key, session_id=f"{project_id}:{session_id}", system_message=system
        ).with_model("openai", "gpt-5.4")
        try:
            reply = await chat.send_message(UserMessage(text=message))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Assistant error: {exc}")

        await self.messages.insert(
            {"project_id": project_id, "session_id": session_id, "role": "assistant", "content": reply}
        )
        return {"reply": reply, "session_id": session_id}
