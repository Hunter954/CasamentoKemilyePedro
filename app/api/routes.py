import os
import hmac

from flask import Blueprint, request, jsonify, current_app
from app import db
from app.models import GiftPurchase, WhatsAppDispatch, WhatsAppWebhookLog
from app.services.mercado_pago import MercadoPagoService
from app.services.whatsapp import normalize_whatsapp_phone, serialize_payload, extract_message_id

api_bp = Blueprint('api', __name__)


@api_bp.route('/whatsapp/campaigns/tick', methods=['POST'])
def campaign_tick():
    secret = current_app.config.get('WA_INTERNAL_TOKEN') or os.getenv('WA_INTERNAL_TOKEN', '')
    received = request.headers.get('X-WA-Internal-Token', '')
    if not secret or not hmac.compare_digest(str(secret).encode(), received.encode()):
        return jsonify({'error': 'Não autorizado.'}), 403
    from app.services.campaign_queue import process_next
    return jsonify(process_next())


@api_bp.route('/whatsapp/contacts/import', methods=['POST'])
def whatsapp_contact_import():
    from app.services.contact_import import import_contacts
    secret = current_app.config.get('WA_INTERNAL_TOKEN') or os.getenv('WA_INTERNAL_TOKEN', '')
    received = request.headers.get('X-WA-Internal-Token', '')
    if not secret or not hmac.compare_digest(str(secret).encode(), received.encode()):
        return jsonify({'error': 'Não autorizado.'}), 403
    if request.content_length and request.content_length > 262144:
        return jsonify({'error': 'Lote muito grande.'}), 413
    try:
        return jsonify(import_contacts(request.get_json(silent=True)))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@api_bp.route('/mercado-pago/webhook', methods=['POST'])
def mercado_pago_webhook():
    data = request.get_json(silent=True) or {}
    payment_id = None
    external_reference = request.args.get('external_reference')
    payment_status = None

    if data.get('data') and isinstance(data['data'], dict):
        payment_id = data['data'].get('id')
        external_reference = external_reference or data['data'].get('external_reference')

    payment_id = payment_id or data.get('id') or request.args.get('data.id') or request.args.get('id')

    if payment_id:
        try:
            payment_data = MercadoPagoService.fetch_payment(payment_id)
            external_reference = external_reference or str(payment_data.get('external_reference') or '')
            payment_status = payment_data.get('status')
        except Exception:
            payment_status = None

    if external_reference and str(external_reference).isdigit():
        purchase = GiftPurchase.query.get(int(external_reference))
        if purchase:
            purchase.mercado_pago_payment_id = str(payment_id or purchase.mercado_pago_payment_id or '')
            if payment_status == 'approved' or not payment_id:
                purchase.status = 'approved'
            elif payment_status:
                purchase.status = payment_status
            db.session.commit()

    return jsonify({'ok': True})


def _payload():
    return request.get_json(silent=True) or request.form.to_dict(flat=True) or {}


def _valid_webhook_request():
    configured_secret = (os.getenv('ZAPI_WEBHOOK_SECRET') or '').strip()
    if not configured_secret:
        return True
    received = (request.headers.get('X-ZAPI-SECRET') or request.args.get('secret') or request.headers.get('Client-Token') or '').strip()
    return bool(received and received == configured_secret)


def _log_webhook(event_type: str, data: dict, notes: str = ''):
    message_id = extract_message_id(data)
    phone = normalize_whatsapp_phone(
        data.get('phone') or data.get('from') or data.get('to') or data.get('mobile') or data.get('chatId') or ''
    )
    log = WhatsAppWebhookLog(
        event_type=event_type,
        provider='zapi',
        external_message_id=message_id,
        phone=phone,
        payload=serialize_payload(data),
        notes=notes or '',
    )
    db.session.add(log)
    return log


def _apply_dispatch_update(data: dict, fallback_status: str):
    message_id = extract_message_id(data)
    phone = normalize_whatsapp_phone(
        data.get('phone') or data.get('from') or data.get('to') or data.get('mobile') or data.get('chatId') or ''
    )
    status = str(data.get('status') or data.get('messageStatus') or fallback_status or '').lower().strip()

    dispatch = None
    if message_id:
        dispatch = WhatsAppDispatch.query.filter_by(provider_message_id=message_id).order_by(WhatsAppDispatch.id.desc()).first()
    if not dispatch and phone:
        dispatch = WhatsAppDispatch.query.filter_by(phone_sent=phone).order_by(WhatsAppDispatch.id.desc()).first()
    if not dispatch:
        return None

    if message_id and not dispatch.provider_message_id:
        dispatch.provider_message_id = message_id
    if phone and not dispatch.phone_sent:
        dispatch.phone_sent = phone

    dispatch.response_body = serialize_payload(data)

    if status in {'sent', 'delivered', 'delivery', 'received', 'read'}:
        dispatch.status = 'sent'
        dispatch.error_message = ''
    elif status in {'error', 'failed', 'fail'}:
        dispatch.status = 'error'
        dispatch.error_message = data.get('reason') or data.get('error') or data.get('message') or 'Falha informada pelo webhook da Z-API.'
    elif status:
        dispatch.status = status[:30]

    return dispatch


@api_bp.route('/zapi/webhook/send', methods=['POST'])
def zapi_webhook_send():
    if not _valid_webhook_request():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = _payload()
    _log_webhook('send', data)
    _apply_dispatch_update(data, 'sent')
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/zapi/webhook/status', methods=['POST'])
def zapi_webhook_status():
    if not _valid_webhook_request():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = _payload()
    _log_webhook('status', data)
    _apply_dispatch_update(data, 'status')
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/zapi/webhook/received', methods=['POST'])
def zapi_webhook_received():
    if not _valid_webhook_request():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = _payload()
    _log_webhook('received', data)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/zapi/webhook/connected', methods=['POST'])
def zapi_webhook_connected():
    if not _valid_webhook_request():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = _payload()
    _log_webhook('connected', data)
    db.session.commit()
    return jsonify({'ok': True})




@api_bp.route('/zapi/webhook/disconnected', methods=['POST'])
def zapi_webhook_disconnected():
    if not _valid_webhook_request():
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    data = _payload()
    _log_webhook('disconnected', data)
    db.session.commit()
    return jsonify({'ok': True})

@api_bp.route('/zapi/webhook/health', methods=['GET'])
def zapi_webhook_health():
    return jsonify({'ok': True, 'service': 'zapi-webhooks'})
