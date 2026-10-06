import requests
from flask import current_app
from app.models import SiteSettings


class MercadoPagoService:
    PREFERENCES_API_URL = 'https://api.mercadopago.com/checkout/preferences'
    PAYMENTS_API_URL = 'https://api.mercadopago.com/v1/payments/{payment_id}'

    @classmethod
    def get_settings(cls):
        return SiteSettings.query.first()

    @classmethod
    def get_access_token(cls):
        settings = cls.get_settings()
        if settings and settings.mercado_pago_enabled and (settings.mercado_pago_access_token or '').strip():
            return settings.mercado_pago_access_token.strip()
        return (current_app.config.get('MERCADO_PAGO_ACCESS_TOKEN') or '').strip()

    @classmethod
    def is_enabled(cls):
        settings = cls.get_settings()
        if settings and settings.mercado_pago_enabled:
            return bool((settings.mercado_pago_access_token or '').strip())
        return bool(cls.get_access_token())

    @classmethod
    def create_preference(cls, purchase, gift_title, success_url, pending_url, failure_url, notification_url):
        if not cls.is_enabled():
            return {
                'enabled': False,
                'sandbox_url': '#',
                'reference': f'LOCAL-{purchase.id}',
                'message': 'Checkout em modo local. Configure e ative o Mercado Pago no painel admin.',
                'category': 'warning',
            }

        payload = {
            'items': [{
                'title': gift_title,
                'quantity': 1,
                'currency_id': 'BRL',
                'unit_price': float(purchase.amount),
            }],
            'payer': {
                'name': purchase.buyer_name,
                'email': purchase.buyer_email,
            },
            'back_urls': {
                'success': success_url,
                'pending': pending_url,
                'failure': failure_url,
            },
            'auto_return': 'approved',
            'external_reference': str(purchase.id),
            'notification_url': notification_url,
        }
        headers = {
            'Authorization': f"Bearer {cls.get_access_token()}",
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(cls.PREFERENCES_API_URL, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
            return {
                'enabled': True,
                'sandbox_url': data.get('init_point') or data.get('sandbox_init_point'),
                'reference': data.get('id', ''),
            }
        except requests.HTTPError as exc:
            body = ''
            try:
                body = exc.response.text
            except Exception:
                body = str(exc)
            current_app.logger.exception('Mercado Pago preference creation failed: %s', body)
            return {
                'enabled': False,
                'sandbox_url': '#',
                'reference': f'ERR-{purchase.id}',
                'message': 'Falha ao iniciar pagamento no Mercado Pago. Verifique token, ambiente e URLs de retorno.',
                'category': 'danger',
            }
        except Exception:
            current_app.logger.exception('Unexpected Mercado Pago error while creating preference')
            return {
                'enabled': False,
                'sandbox_url': '#',
                'reference': f'ERR-{purchase.id}',
                'message': 'Erro interno ao preparar o pagamento. Confira os logs do Railway.',
                'category': 'danger',
            }

    @classmethod
    def fetch_payment(cls, payment_id):
        if not payment_id or not cls.is_enabled():
            return {}
        headers = {'Authorization': f"Bearer {cls.get_access_token()}"}
        response = requests.get(cls.PAYMENTS_API_URL.format(payment_id=payment_id), headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
