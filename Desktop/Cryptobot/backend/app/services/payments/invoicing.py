import logging
from datetime import datetime
from decimal import Decimal

from app.models.subscription import SubscriptionPlan

logger = logging.getLogger("tbx.payments.invoicing")

VAT_RATES = {
    1: 0,   # Без НДС
    2: 0,   # 0%
    3: 10,  # 10%
    4: 20,  # 20%
    5: 10 / 110,  # Расчётная 10/110
    6: 20 / 120,  # Расчётная 20/120
}


def calculate_vat(amount: Decimal, vat_rate: int = 4) -> tuple[Decimal, Decimal]:
    if vat_rate in (1, 2):
        return amount, Decimal("0")
    if vat_rate in (5, 6):
        rate = Decimal(str(VAT_RATES[vat_rate]))
        vat = (amount * rate).quantize(Decimal("0.01"))
        base = amount - vat
        return base, vat
    rate = Decimal(str(VAT_RATES.get(vat_rate, 20)))
    vat = (amount * rate / 100).quantize(Decimal("0.01"))
    base = (amount - vat).quantize(Decimal("0.01"))
    return amount, vat


def generate_invoice_number(seq: int) -> str:
    now = datetime.utcnow()
    return f"TBX-{now.year}{now.month:02d}-{seq:05d}"


def generate_invoice_html(
    invoice_number: str,
    company_name: str,
    company_inn: str,
    company_kpp: str | None,
    plan: SubscriptionPlan,
    amount: Decimal,
    vat_rate: int,
    date: datetime,
) -> str:
    base, vat = calculate_vat(amount, vat_rate)
    total = amount

    plan_names = {
        SubscriptionPlan.TRADER: "TBX Trader (месячная подписка)",
        SubscriptionPlan.INVESTOR_PRO: "TBX Investor Pro (месячная подписка)",
        SubscriptionPlan.PROP_FIRM_MASTER: "TBX Prop Firm Master (месячная подписка)",
        SubscriptionPlan.ENTERPRISE: "TBX Enterprise (индивидуальный)",
    }

    vat_label = {
        1: "Без НДС",
        2: "НДС 0%",
        3: "НДС 10%",
        4: "НДС 20%",
    }.get(vat_rate, f"НДС {VAT_RATES.get(vat_rate, 20)}%")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Счёт {invoice_number}</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
.header {{ border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px; }}
.header h1 {{ font-size: 24px; margin: 0; }}
.header .number {{ color: #666; font-size: 14px; }}
.company-info {{ margin-bottom: 30px; line-height: 1.6; }}
table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
th {{ background: #f5f5f5; }}
.total {{ text-align: right; font-size: 18px; font-weight: bold; margin-top: 20px; }}
.footer {{ margin-top: 50px; font-size: 12px; color: #888; border-top: 1px solid #ddd; padding-top: 20px; }}
</style></head>
<body>
<div class="header">
    <h1>Счёт на оплату</h1>
    <div class="number">№ {invoice_number} от {date.strftime('%d.%m.%Y')}</div>
</div>

<div class="company-info">
    <strong>Поставщик:</strong> TBX Trade Terminal (ИП/ООО)<br>
    <strong>ИНН:</strong> ___________ &nbsp;&nbsp; <strong>КПП:</strong> ___________<br>
    <strong>Покупатель:</strong> {company_name}<br>
    <strong>ИНН:</strong> {company_inn}{f' &nbsp;&nbsp; <strong>КПП:</strong> {company_kpp}' if company_kpp else ''}
</div>

<table>
    <tr><th>№</th><th>Наименование</th><th>Кол-во</th><th>Цена</th><th>Сумма</th></tr>
    <tr>
        <td>1</td>
        <td>{plan_names.get(plan, plan.value)}</td>
        <td>1</td>
        <td>{base:.2f} ₽</td>
        <td>{base:.2f} ₽</td>
    </tr>
</table>

<div class="total">
    Итого: {base:.2f} ₽<br>
    {vat_label}: {vat:.2f} ₽<br>
    <strong>Всего к оплате: {total:.2f} ₽</strong>
</div>

<div class="footer">
    Счёт действителен в течение 5 банковских дней.<br>
    Оплата данного счёта означает согласие с условиями договора-оферты.<br>
    Товар/услуга передаётся после зачисления денежных средств на расчётный счёт.
</div>
</body></html>"""
