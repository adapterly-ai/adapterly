"""Stripe billing endpoints: checkout, webhook, portal, plan info."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models.account import Account, PLAN_LIMITS
from ..models.api_key import APIKey
from .deps import get_api_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan: str  # "pro" | "team"
    success_url: str = "https://adapterly.ai/billing?success=true"
    cancel_url: str = "https://adapterly.ai/billing?canceled=true"


class PlanInfo(BaseModel):
    plan: str
    limits: dict
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    usage_reset_at: str | None


def _get_stripe():
    """Initialize stripe with current settings."""
    settings = get_settings()
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def _price_id_for_plan(plan: str) -> str:
    """Map plan name to Stripe price ID."""
    settings = get_settings()
    mapping = {
        "pro": settings.STRIPE_PRICE_PRO_MONTHLY,
        "team": settings.STRIPE_PRICE_TEAM_MONTHLY,
    }
    price_id = mapping.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"No Stripe price configured for plan '{plan}'")
    return price_id


@router.get("/usage")
async def get_usage_stats(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get current usage stats for the account."""
    from ..billing.usage import get_usage
    return await get_usage(db, api_key.account_id)


@router.get("/plan", response_model=PlanInfo)
async def get_plan(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get current account plan and limits."""
    result = await db.execute(select(Account).where(Account.id == api_key.account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return PlanInfo(
        plan=account.plan,
        limits=account.limits,
        stripe_customer_id=account.stripe_customer_id,
        stripe_subscription_id=account.stripe_subscription_id,
        usage_reset_at=account.usage_reset_at.isoformat() if account.usage_reset_at else None,
    )


@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutRequest,
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for upgrading plan."""
    s = _get_stripe()

    if body.plan not in ("pro", "team"):
        raise HTTPException(status_code=400, detail="Can only checkout pro or team plans")

    result = await db.execute(select(Account).where(Account.id == api_key.account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Create or reuse Stripe customer
    if not account.stripe_customer_id:
        customer = s.Customer.create(
            metadata={"account_id": account.id, "account_slug": account.slug},
        )
        account.stripe_customer_id = customer.id
        await db.commit()

    price_id = _price_id_for_plan(body.plan)

    session = s.checkout.Session.create(
        customer=account.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        metadata={"account_id": account.id, "plan": body.plan},
    )

    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/portal")
async def create_portal_session(
    api_key: APIKey = Depends(get_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Customer Portal session for managing subscription."""
    s = _get_stripe()

    result = await db.execute(select(Account).where(Account.id == api_key.account_id))
    account = result.scalar_one_or_none()
    if not account or not account.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    session = s.billing_portal.Session.create(
        customer=account.stripe_customer_id,
        return_url="https://adapterly.ai/billing",
    )

    return {"portal_url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    settings = get_settings()
    s = _get_stripe()

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = s.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event["type"]
    data = event["data"]["object"]

    # Import here to avoid circular deps
    from ..database import get_session_factory
    factory = get_session_factory()

    async with factory() as db:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(db, data)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(db, data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(db, data)
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(db, data)
        else:
            logger.debug(f"Unhandled webhook event: {event_type}")

        await db.commit()

    return JSONResponse({"received": True})


async def _handle_checkout_completed(db: AsyncSession, data: dict):
    """Activate plan after successful checkout."""
    account_id = data.get("metadata", {}).get("account_id")
    plan = data.get("metadata", {}).get("plan")
    subscription_id = data.get("subscription")

    if not account_id or not plan:
        logger.warning("Checkout completed without account_id/plan metadata")
        return

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        logger.warning(f"Account {account_id} not found for checkout")
        return

    account.plan = plan
    account.stripe_subscription_id = subscription_id
    account.usage_reset_at = datetime.now(timezone.utc)
    logger.info(f"Account {account.slug} upgraded to {plan}")


async def _handle_subscription_updated(db: AsyncSession, data: dict):
    """Update plan when subscription changes."""
    customer_id = data.get("customer")
    if not customer_id:
        return

    result = await db.execute(select(Account).where(Account.stripe_customer_id == customer_id))
    account = result.scalar_one_or_none()
    if not account:
        return

    status = data.get("status")
    if status in ("active", "trialing"):
        # Subscription is active — plan is managed via metadata
        pass
    elif status in ("canceled", "unpaid", "past_due"):
        account.plan = "free"
        account.stripe_subscription_id = None
        logger.info(f"Account {account.slug} downgraded to free (status={status})")


async def _handle_subscription_deleted(db: AsyncSession, data: dict):
    """Downgrade to free when subscription is canceled."""
    customer_id = data.get("customer")
    if not customer_id:
        return

    result = await db.execute(select(Account).where(Account.stripe_customer_id == customer_id))
    account = result.scalar_one_or_none()
    if not account:
        return

    account.plan = "free"
    account.stripe_subscription_id = None
    logger.info(f"Account {account.slug} subscription deleted, downgraded to free")


async def _handle_invoice_paid(db: AsyncSession, data: dict):
    """Reset usage counter on successful invoice payment (monthly renewal)."""
    customer_id = data.get("customer")
    if not customer_id:
        return

    result = await db.execute(select(Account).where(Account.stripe_customer_id == customer_id))
    account = result.scalar_one_or_none()
    if not account:
        return

    account.usage_reset_at = datetime.now(timezone.utc)
    logger.info(f"Account {account.slug} usage reset (invoice paid)")
