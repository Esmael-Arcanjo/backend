"""Internal LEAMSE Email API sender for platform emails (welcome, payment, trial).

Entrega direta via Resend (RESEND_API_KEY / RESEND_FROM_EMAIL). Nunca aceita HTML do usuário (G4). Tudo é template
server-side com variáveis interpoladas via escape().
"""
import logging
from datetime import datetime, timezone
from html import escape

from app.core.database import db
from app.core.mailer import send_via_resend
from app.modules.email.guardrails import assert_safe_email

log = logging.getLogger("leamse.email.internal")


def _welcome_html(v: dict) -> str:
    name = escape(str(v.get("name", "")))
    service = escape(str(v.get("service", "")))
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:32px;'
        'font-family:Arial,sans-serif;max-width:600px">'
        f'<h1 style="margin:0 0 16px;color:#F97316">Bem-vindo à LEAMSE, {name}!</h1>'
        f'<p style="line-height:1.6">Seu workspace LEAMSE para <strong>{service}</strong> '
        'está pronto para uso.</p>'
        '<p style="line-height:1.6">Você tem <strong>7 dias grátis</strong> para testar tudo. '
        'Depois desse período, cobramos automaticamente no cartão cadastrado. '
        'Você pode cancelar a qualquer momento sem burocracia.</p>'
        '<p style="line-height:1.6"><strong>Próximos passos:</strong></p>'
        '<ul style="line-height:1.7"><li>Acesse seu painel</li>'
        '<li>Configure sua marca</li><li>Explore a documentação</li></ul>'
        '<p style="font-size:12px;color:#888;margin-top:32px">Enviado por LEAMSE. '
        'Nunca pedimos sua senha ou dados do cartão por email.</p>'
        '</td></tr></table>'
    )


def _payment_html(v: dict) -> str:
    service = escape(str(v.get("service", "")))
    amount = escape(str(v.get("amount_formatted", "")))
    interval = escape(str(v.get("interval", "")))
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:32px;'
        'font-family:Arial,sans-serif;max-width:600px">'
        '<h1 style="margin:0 0 16px;color:#10B981">Pagamento confirmado</h1>'
        f'<p style="line-height:1.6">Recebemos o pagamento de <strong>{amount}</strong> '
        f'referente ao seu plano <strong>{service}</strong> ({interval}).</p>'
        '<p style="line-height:1.6">Seu acesso está ativo e sua próxima cobrança acontecerá '
        'ao final do período. Guarde este email como comprovante.</p>'
        '<p style="font-size:12px;color:#888;margin-top:32px">Enviado por LEAMSE.</p>'
        '</td></tr></table>'
    )


def _trial_ending_html(v: dict) -> str:
    service = escape(str(v.get("service", "")))
    days = escape(str(v.get("days_left", "")))
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:32px;'
        'font-family:Arial,sans-serif;max-width:600px">'
        f'<h1 style="margin:0 0 16px;color:#F97316">Seu trial acaba em {days} dias</h1>'
        f'<p style="line-height:1.6">O período gratuito do seu plano <strong>{service}</strong> '
        f'termina em {days} dias.</p>'
        '<p style="line-height:1.6">Para continuar usando sem interrupção, confira se seu cartão '
        'está válido. Prefere cancelar? Sem problema — basta acessar Configurações › Plano e cobrança.</p>'
        '<p style="font-size:12px;color:#888;margin-top:32px">Enviado por LEAMSE.</p>'
        '</td></tr></table>'
    )


def _card_recovery_html(v: dict) -> str:
    service = escape(str(v.get("service", "")))
    return (
        '<table role="presentation" width="100%"><tr><td style="padding:32px;'
        'font-family:Arial,sans-serif;max-width:600px">'
        '<h1 style="margin:0 0 16px;color:#EF4444">Falha na renovação do seu plano</h1>'
        f'<p style="line-height:1.6">Tentamos renovar seu plano <strong>{service}</strong> mas o cartão foi recusado.</p>'
        '<p style="line-height:1.6">Sem estresse: você pode <strong>atualizar o cartão em Configurações › Plano e cobrança</strong> '
        'para não perder acesso. Vamos tentar novamente em algumas horas.</p>'
        '<p style="font-size:12px;color:#888;margin-top:32px">Enviado por LEAMSE.</p>'
        '</td></tr></table>'
    )


TEMPLATES = {
    "welcome": {"subject": "Bem-vindo à LEAMSE, {name}", "html": _welcome_html},
    "payment_success": {"subject": "Pagamento confirmado — LEAMSE", "html": _payment_html},
    "trial_ending": {"subject": "Seu trial LEAMSE acaba em breve", "html": _trial_ending_html},
    "card_recovery": {"subject": "Ação necessária — atualize seu cartão LEAMSE", "html": _card_recovery_html},
}


async def send_internal(to: str, template: str, variables: dict,
                        organization_id: str | None = None) -> str | None:
    """Send a platform email through the LEAMSE Email API. Best-effort — never raises."""
    t = TEMPLATES.get(template)
    if not t or not to:
        return None
    try:
        subject = t["subject"].format(**{k: str(v) for k, v in variables.items() if isinstance(v, (str, int, float))})
    except Exception:
        subject = t["subject"]
    html = t["html"](variables)
    doc_ins = await db.email_logs.insert_one({
        "project_id": None, "organization_id": organization_id,
        "to": to, "subject": subject, "template_slug": template,
        "status": "queued", "variables": variables, "attempts": 0,
        "created_at": datetime.now(timezone.utc),
    })
    log_id = str(doc_ins.inserted_id)

    # Guardrail gate (G2/G3) — must pass on every send.
    try:
        assert_safe_email(subject, html)
    except ValueError as e:
        await db.email_logs.update_one({"_id": doc_ins.inserted_id},
                                       {"$set": {"status": "failed", "error": str(e)}})
        log.error("guardrail block for %s: %s", template, e)
        return None

    provider_id, error = await send_via_resend(to, subject, html)
    if error:
        await db.email_logs.update_one(
            {"_id": doc_ins.inserted_id},
            {"$set": {"status": "failed", "attempts": 1, "error": error}},
        )
        return None
    await db.email_logs.update_one(
        {"_id": doc_ins.inserted_id},
        {"$set": {"status": "sent", "provider_id": provider_id, "attempts": 1}},
    )
    return log_id
