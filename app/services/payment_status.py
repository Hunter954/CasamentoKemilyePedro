from decimal import Decimal, InvalidOperation
from app.models import GiftPurchase
from app.services.guestbook import attach_message

PAYMENT_STATES = {'pending', 'in_process', 'authorized', 'approved', 'rejected', 'cancelled', 'refunded', 'charged_back', 'in_mediation'}


def apply_verified_payment(data):
    """Use only a payment fetched from MP with the server access token."""
    if not isinstance(data, dict):
        return None
    reference = str(data.get('external_reference') or '')
    payment_id = str(data.get('id') or '')
    status = data.get('status')
    if not reference.isascii() or not reference.isdigit() or len(reference) > 18 or not payment_id.isdigit() or status not in PAYMENT_STATES:
        return None
    purchase = GiftPurchase.query.filter_by(id=int(reference)).with_for_update().first()
    if not purchase or data.get('currency_id') != 'BRL':
        return None
    try:
        amount = Decimal(str(data.get('transaction_amount')))
        expected = Decimal(str(purchase.amount))
        if not amount.is_finite() or amount.quantize(Decimal('.01')) != expected.quantize(Decimal('.01')):
            return None
    except (InvalidOperation, ValueError, TypeError):
        return None
    # A verified approval must not regress due to an older pending callback.
    if purchase.status == 'approved' and purchase.payment_verified:
        if status in ('pending', 'in_process', 'authorized') or (purchase.mercado_pago_payment_id != payment_id and status != 'approved'):
            return purchase
    purchase.mercado_pago_payment_id = payment_id
    purchase.status = status
    purchase.payment_verified = True
    if status == 'approved':
        attach_message(purchase, 'purchase')
    return purchase
