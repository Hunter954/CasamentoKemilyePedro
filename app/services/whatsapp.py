import json
import random
import re
import time

import requests
from flask import current_app

from app import db
from app.models import ContactLead, SiteSettings
from app.utils import to_public_media_url


class WhatsAppConfigError(Exception):
    pass


class WhatsAppSendError(Exception):
    pass


def _settings():
    return SiteSettings.query.first()


def normalize_whatsapp_phone(value: str) -> str:
    digits = ''.join(char for char in str(value or '') if char.isdigit())
    if not digits:
        return ''
    if digits.startswith('55') and len(digits) in {12, 13}:
        return digits
    if len(digits) in {10, 11} and not str(value or '').strip().startswith('+'):
        return f'55{digits}'
    return digits


def generate_confirmation_code(length: int = 6) -> str:
    return ''.join(str(random.randint(0, 9)) for _ in range(max(4, length)))


def get_or_create_contact_code(contact, commit: bool = False) -> str:
    current = (getattr(contact, 'confirmation_code', '') or '').strip()
    if current:
        return current
    while True:
        code = generate_confirmation_code()
        existing = ContactLead.query.filter(ContactLead.confirmation_code == code, ContactLead.id != contact.id).first()
        if not existing:
            contact.confirmation_code = code
            break
    if commit:
        db.session.commit()
    return contact.confirmation_code


def ensure_all_contact_codes(commit: bool = False):
    changed = False
    contacts = ContactLead.query.order_by(ContactLead.id.asc()).all()
    used = {((c.confirmation_code or '').strip()): c.id for c in contacts if (c.confirmation_code or '').strip()}
    for contact in contacts:
        code = (contact.confirmation_code or '').strip()
        if not code or used.get(code) != contact.id:
            while True:
                new_code = generate_confirmation_code()
                if new_code not in used:
                    contact.confirmation_code = new_code
                    used[new_code] = contact.id
                    changed = True
                    break
    if changed and commit:
        db.session.commit()
    return changed


def _bridge_url() -> str:
    return str(current_app.config.get('WHATSAPP_BRIDGE_URL') or 'http://127.0.0.1:3100').rstrip('/')


def _bridge_request(method: str, path: str, payload=None, timeout=35):
    try:
        response = requests.request(method, f'{_bridge_url()}{path}', json=payload, timeout=timeout)
        try:
            data = response.json()
        except ValueError:
            data = {'error': response.text or 'Resposta inválida do serviço WhatsApp.'}
        if response.ok:
            return data
        raise WhatsAppSendError(data.get('error') or data.get('message') or 'Falha no serviço WhatsApp.')
    except requests.RequestException as exc:
        raise WhatsAppConfigError(
            'O motor local do WhatsApp não respondeu. Confira se o processo Node/Baileys iniciou junto com o site.'
        ) from exc


def get_instance_status():
    data = _bridge_request('GET', '/status', timeout=8)
    return {
        **data,
        'connected': bool(data.get('ready')),
        'smartphoneConnected': bool(data.get('ready')),
    }


def get_instance_data():
    data = get_instance_status()
    return {
        'phone': data.get('phone') or '',
        'name': 'Kemily & Pedro - Baileys',
        'engine': data.get('engine', 'baileys'),
        'authStore': data.get('authStore', 'PostgreSQL'),
        'sessionId': data.get('sessionId', ''),
        'status': data.get('status', ''),
        'connectedAt': data.get('connectedAt'),
        'lastQrAt': data.get('lastQrAt'),
    }


def get_qrcode_image_base64():
    data = _bridge_request('GET', '/status', timeout=8)
    if not data.get('ready') and not data.get('qr') and not data.get('starting'):
        try:
            _bridge_request('POST', '/start', {}, timeout=12)
            time.sleep(0.5)
            data = _bridge_request('GET', '/status', timeout=8)
        except Exception:
            pass
    return str(data.get('qr') or '')


def restart_instance():
    _bridge_request('POST', '/disconnect', {}, timeout=10)
    return _bridge_request('POST', '/start', {}, timeout=15)


def disconnect_instance():
    return _bridge_request('POST', '/reset', {}, timeout=15)


def configure_instance_webhooks(base_url: str):
    return {'ok': True, 'message': 'Baileys não usa webhooks externos. A sessão fica persistida no PostgreSQL.'}


def get_queue_count() -> int:
    return 0


def get_queue_snapshot():
    return {'engine': 'baileys', 'queue': 'envio direto pelo processo local'}


def _post_send_text(phone: str, message: str, delay_seconds: int | None = None):
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        raise WhatsAppSendError('Telefone inválido para envio.')
    data = _bridge_request('POST', '/send-text', {'phone': '+' + normalized, 'message': message}, timeout=35)
    return {'ok': True, 'response': data, 'message_id': data.get('messageId', ''), 'phone': normalized}


def _post_send_image(phone: str, image_url: str, caption: str = '', delay_seconds: int | None = None):
    normalized = normalize_whatsapp_phone(phone)
    if not normalized:
        raise WhatsAppSendError('Telefone inválido para envio da imagem.')
    if not image_url:
        raise WhatsAppSendError('Imagem da campanha não encontrada.')
    data = _bridge_request('POST', '/send-image', {'phone': '+' + normalized, 'image': image_url, 'caption': caption or ''}, timeout=45)
    return {'ok': True, 'response': data, 'message_id': data.get('messageId', ''), 'phone': normalized}


def send_test_message(phone: str, message: str):
    return _post_send_text(phone=phone, message=message)


def render_campaign_message(template: str, contact, settings=None, site_url: str = '') -> str:
    settings = settings or _settings()
    content = str(template or '').strip()
    if not content:
        return ''
    wedding_date = settings.wedding_date.strftime('%d/%m/%Y') if settings and settings.wedding_date else ''
    code = get_or_create_contact_code(contact)
    replacements = {
        '%contato%': (getattr(contact, 'name', '') or '').strip(),
        '%codigo%': code,
        '%nome_noivos%': (getattr(settings, 'couple_names', '') or '').strip() if settings else '',
        '%data_casamento%': wedding_date,
        '%horario_casamento%': (getattr(settings, 'wedding_time', '') or '').strip() if settings else '',
        '%local_casamento%': (getattr(settings, 'wedding_location_name', '') or '').strip() if settings else '',
        '%endereco_casamento%': (getattr(settings, 'wedding_address', '') or '').strip() if settings else '',
        '%cidade_casamento%': (getattr(settings, 'wedding_city', '') or '').strip() if settings else '',
        '%rota_url%': (getattr(settings, 'route_url', '') or '').strip() if settings else '',
        '%site_url%': (site_url or '').strip(),
    }
    for key, value in replacements.items():
        content = content.replace(key, value)
    return re.sub(r'\n{3,}', '\n\n', content).strip()


def serialize_payload(data):
    try:
        return json.dumps(data or {}, ensure_ascii=False)
    except Exception:
        return str(data or '')


def extract_message_id(data) -> str:
    """Extrai o ID da mensagem de payloads do Baileys e mantém compatibilidade com webhooks legados."""
    if not isinstance(data, dict):
        return ''

    candidates = [
        data.get('messageId'),
        data.get('message_id'),
        data.get('id'),
        data.get('zaapId'),
    ]

    key = data.get('key')
    if isinstance(key, dict):
        candidates.extend([key.get('id'), key.get('messageId')])

    message = data.get('message')
    if isinstance(message, dict):
        candidates.extend([message.get('id'), message.get('messageId')])
        message_key = message.get('key')
        if isinstance(message_key, dict):
            candidates.extend([message_key.get('id'), message_key.get('messageId')])

    response = data.get('response')
    if isinstance(response, dict):
        candidates.extend([response.get('id'), response.get('messageId')])
        response_key = response.get('key')
        if isinstance(response_key, dict):
            candidates.extend([response_key.get('id'), response_key.get('messageId')])

    for value in candidates:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''
