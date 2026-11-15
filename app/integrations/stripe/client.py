import logging
from typing import Optional

import stripe
from fastapi import HTTPException

from app.core.config.settings import settings

logger = logging.getLogger("stripe")
stripe.api_key = settings.stripe_secret_key


def create_subscription_checkout(lookup_key: str, origin_url: str, customer_email: str, metadata: dict) -> stripe.checkout.Session:
    prices = stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1).data
    if not prices:
        raise HTTPException(status_code=503, detail="Plano indisponível no provedor de pagamento")
    kwargs = dict(
        line_items=[{"price": prices[0].id, "quantity": 1}],
        mode="subscription",
        success_url=f"{origin_url}/pagamento/sucesso?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{origin_url}/pagamento/cancelado",
        customer_email=customer_email,
        client_reference_id=metadata["subscription_id"],
        metadata=metadata,
        subscription_data={"metadata": metadata},
    )
    if settings.stripe_tax_mode == "calc_only":
        try:
            return stripe.checkout.Session.create(**kwargs, automatic_tax={"enabled": True},
                                                  billing_address_collection="required")
        except stripe.error.InvalidRequestError as e:
            logger.warning("Stripe Tax unavailable, creating checkout without tax: %s", e.user_message)
    return stripe.checkout.Session.create(**kwargs)


def retrieve_session(session_id: str) -> Optional[stripe.checkout.Session]:
    try:
        return stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError:
        return None


def construct_event(payload: bytes, signature: str):
    return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)


def cancel_at_period_end(stripe_subscription_id: str):
    return stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=True)


def resume(stripe_subscription_id: str):
    return stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=False)
