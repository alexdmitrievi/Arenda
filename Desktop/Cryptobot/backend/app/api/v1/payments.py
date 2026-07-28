import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.subscription import (
    Invoice,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.models.user import User
from app.services.payments.invoicing import generate_invoice_html, generate_invoice_number
from app.services.payments.recurring import process_recurring_payments
from app.services.payments.yookassa import (
    capture_payment,
    create_auto_payment,
    create_payment,
    get_plan_price,
    verify_webhook_signature,
)

logger = logging.getLogger("tbx.api.payments")

router = APIRouter()


class CreatePaymentRequest(BaseModel):
    plan: SubscriptionPlan
    save_payment_method: bool = False
    return_url: str = Field(default="https://tbx.app/payment/success")


class PaymentResponse(BaseModel):
    payment_id: str
    confirmation_url: str
    amount: str
    currency: str
    plan: str
    status: str


class CreateInvoiceRequest(BaseModel):
    plan: SubscriptionPlan
    company_name: str = Field(min_length=2, max_length=255)
    company_inn: str = Field(min_length=10, max_length=12)
    company_kpp: str | None = Field(default=None, max_length=9)


class PlanInfo(BaseModel):
    plan: str
    name: str
    price: str
    price_monthly: str
    features: list[str]


@router.get("/plans", response_model=list[PlanInfo])
async def list_plans():
    from app.models.subscription import PLAN_FEATURES

    plan_names = {
        SubscriptionPlan.DEMO: "Demo",
        SubscriptionPlan.TRADER: "Trader",
        SubscriptionPlan.INVESTOR_PRO: "Investor Pro",
        SubscriptionPlan.PROP_FIRM_MASTER: "Prop Firm Master",
        SubscriptionPlan.ENTERPRISE: "Enterprise",
    }
    result = []
    for plan in SubscriptionPlan:
        price = get_plan_price(plan)
        result.append(
            PlanInfo(
                plan=plan.value,
                name=plan_names.get(plan, plan.value),
                price=f"{price} ₽",
                price_monthly=f"{price} ₽/мес",
                features=PLAN_FEATURES.get(plan, []),
            )
        )
    return result


@router.post("/create", response_model=PaymentResponse)
async def create_payment_endpoint(
    request: CreatePaymentRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    if request.plan == SubscriptionPlan.DEMO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo plan is free — no payment needed",
        )

    price = get_plan_price(request.plan)
    if price <= 0 and request.plan != SubscriptionPlan.ENTERPRISE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan: {request.plan.value}",
        )

    if request.plan == SubscriptionPlan.ENTERPRISE:
        return PaymentResponse(
            payment_id="enterprise",
            confirmation_url="https://tbx.app/contact",
            amount="0",
            currency="RUB",
            plan="enterprise",
            status="contact_sales",
        )

    description = f"TBX {request.plan.value} — подписка на месяц"

    try:
        yk_data = await create_payment(
            amount=price,
            description=description,
            return_url=request.return_url,
            plan=request.plan,
            save_payment_method=request.save_payment_method,
        )
    except Exception as e:
        logger.error("YooKassa create_payment error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment service temporarily unavailable",
        )

    payment = Payment(
        user_id=current_user.id,
        yookassa_payment_id=yk_data["id"],
        idempotency_key=yk_data.get("idempotency_key"),
        amount=price,
        currency="RUB",
        vat_rate=4,
        status=PaymentStatus.PENDING,
        description=description,
        plan=request.plan,
    )
    db.add(payment)
    await db.flush()

    return PaymentResponse(
        payment_id=yk_data["id"],
        confirmation_url=yk_data["confirmation"]["confirmation_url"],
        amount=f"{price:.2f}",
        currency="RUB",
        plan=request.plan.value,
        status=yk_data["status"],
    )


@router.post("/webhook")
async def yookassa_webhook(
    request: Request,
    db: DbSession,
):
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not verify_webhook_signature(body, signature):
        logger.warning("YooKassa webhook: invalid signature")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    data = await request.json()
    event = data.get("event", "")
    obj = data.get("object", {})

    logger.info("YooKassa webhook: event=%s payment_id=%s status=%s",
                event, obj.get("id"), obj.get("status"))

    if event == "payment.succeeded":
        yk_payment_id = obj.get("id")
        result = await db.execute(
            select(Payment).where(Payment.yookassa_payment_id == yk_payment_id)
        )
        payment = result.scalar_one_or_none()

        if payment is None:
            logger.warning("Payment not found for yookassa_id=%s", yk_payment_id)
            return {"status": "ignored"}

        if payment.status == PaymentStatus.SUCCEEDED:
            return {"status": "already_processed"}

        payment.status = PaymentStatus.SUCCEEDED
        paid = bool(obj.get("paid", False))

        if paid and payment.plan:
            pm_data = obj.get("payment_method", {})
            pm_saved = pm_data.get("saved", False)

            sub_result = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == payment.user_id,
                    Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
                )
            )
            existing_sub = sub_result.scalar_one_or_none()

            if existing_sub:
                existing_sub.plan = payment.plan
                existing_sub.status = SubscriptionStatus.ACTIVE
                existing_sub.expires_at = (
                    existing_sub.expires_at or datetime.now(timezone.utc)
                ) + timedelta(days=30)
            else:
                new_sub = Subscription(
                    user_id=payment.user_id,
                    plan=payment.plan,
                    status=SubscriptionStatus.ACTIVE,
                    started_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                    auto_renew=bool(pm_saved),
                    yookassa_payment_method_id=pm_data.get("id") if pm_saved else None,
                )
                db.add(new_sub)

            payment.subscription_id = str(existing_sub.id if existing_sub else new_sub.id)

    elif event == "payment.canceled":
        yk_payment_id = obj.get("id")
        result = await db.execute(
            select(Payment).where(Payment.yookassa_payment_id == yk_payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = PaymentStatus.CANCELED

    elif event == "refund.succeeded":
        yk_payment_id = obj.get("payment_id")
        result = await db.execute(
            select(Payment).where(Payment.yookassa_payment_id == yk_payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = PaymentStatus.REFUNDED

    return {"status": "ok"}


@router.post("/invoice", response_model=dict)
async def create_invoice(
    request: CreateInvoiceRequest,
    current_user: CurrentUser,
    db: DbSession,
):
    price = get_plan_price(request.plan)
    if price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create invoice for free plan",
        )

    count_result = await db.execute(select(Invoice).order_by(Invoice.created_at.desc()).limit(1))
    last_inv = count_result.scalar_one_or_none()
    seq = 1
    if last_inv:
        try:
            seq = int(last_inv.invoice_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1

    invoice_number = generate_invoice_number(seq)
    html = generate_invoice_html(
        invoice_number=invoice_number,
        company_name=request.company_name,
        company_inn=request.company_inn,
        company_kpp=request.company_kpp,
        plan=request.plan,
        amount=price,
        vat_rate=4,
        date=datetime.now(timezone.utc),
    )

    invoice = Invoice(
        user_id=current_user.id,
        invoice_number=invoice_number,
        company_name=request.company_name,
        company_inn=request.company_inn,
        company_kpp=request.company_kpp,
        amount=price,
        vat_rate=4,
        vat_amount=price * Decimal("0.20"),
        total=price,
    )
    db.add(invoice)
    await db.flush()

    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice_number,
        "amount": f"{price:.2f}",
        "vat": f"{price * Decimal('0.20'):.2f}",
        "total": f"{price:.2f}",
        "html": html,
    }


@router.get("/subscription")
async def get_my_subscription(
    current_user: CurrentUser,
    db: DbSession,
):
    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == current_user.id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
        )
        .order_by(Subscription.created_at.desc())
    )
    sub = result.scalar_one_or_none()

    if sub is None:
        return {
            "plan": "demo",
            "status": "inactive",
            "expires_at": None,
            "auto_renew": False,
        }

    return {
        "plan": sub.plan.value,
        "status": sub.status.value,
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        "auto_renew": sub.auto_renew,
    }


@router.post("/trial/start")
async def start_trial(
    current_user: CurrentUser,
    db: DbSession,
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == current_user.id,
            Subscription.trial_used == True,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Trial already used",
        )

    trial = Subscription(
        user_id=current_user.id,
        plan=SubscriptionPlan.TRADER,
        status=SubscriptionStatus.TRIAL,
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        trial_used=True,
    )
    db.add(trial)
    await db.flush()

    return {
        "plan": "trader",
        "status": "trial",
        "expires_at": trial.expires_at.isoformat(),
        "days_left": 7,
    }


@router.get("/payment-history")
async def get_payment_history(
    current_user: CurrentUser,
    db: DbSession,
):
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == current_user.id)
        .order_by(Payment.created_at.desc())
        .limit(50)
    )
    payments = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "amount": str(p.amount),
            "currency": p.currency,
            "status": p.status.value,
            "plan": p.plan.value if p.plan else None,
            "created_at": p.created_at.isoformat(),
        }
        for p in payments
    ]
