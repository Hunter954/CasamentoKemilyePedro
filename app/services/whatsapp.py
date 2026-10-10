import json
import random
import re
import time
from datetime import datetime
from typing import Iterable

import requests
from flask import current_app

from app import db
from app.models import ContactLead, SiteSettings, WhatsAppDispatch
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


def send_campaign_messages(campaign, contacts: Iterable, tag_filter: str | None = None, send_scope: str = 'unsent', settings=None, site_url: str = '', batch_size: int | None = None, max_caption_length: int = 1024):
    status = get_instance_status()
    if not status.get('connected'):
        raise WhatsAppConfigError('WhatsApp desconectado. Abra “Conexão WhatsApp” no painel e leia o QR Code primeiro.')

    results, processed = [], 0
    settings = settings or _settings()
    image_url = to_public_media_url(getattr(campaign, 'image_path', '') or '', site_url=site_url)
    try:
        batch_size = max(1, min(int(batch_size), 50)) if batch_size is not None else None
    except (TypeError, ValueError):
        batch_size = None
    delay = max(0.8, min(float(current_app.config.get('WHATSAPP_SEND_DELAY', 1.2)), 10.0))

    for contact in contacts:
        if tag_filter and tag_filter != 'todos' and (contact.tag or '').strip().lower() != tag_filter.strip().lower():
            results.append({'contact': contact, 'status': 'skipped', 'reason': 'tag'}); continue
        existing = WhatsAppDispatch.query.filter_by(campaign_id=campaign.id, contact_id=contact.id).first()
        if send_scope == 'unsent' and existing:
            results.append({'contact': contact, 'status': 'skipped', 'reason': 'already_processed'}); continue
        if send_scope == 'errors' and (not existing or existing.status != 'error'):
            results.append({'contact': contact, 'status': 'skipped', 'reason': 'not_error'}); continue
        if send_scope == 'all' and existing and existing.status in {'sent','delivered','read'}:
            results.append({'contact': contact, 'status': 'skipped', 'reason': 'already_sent'}); continue
        if not existing:
            existing = WhatsAppDispatch(campaign_id=campaign.id, contact_id=contact.id)
            db.session.add(existing)

        existing.phone_sent = normalize_whatsapp_phone(contact.phone)
        message = render_campaign_message(campaign.message, contact, settings, site_url)
        try:
            if image_url and len(message) <= max_caption_length:
                response = _post_send_image(contact.phone, image_url, message)
                mode = 'image_with_caption'
            elif image_url:
                image_response = _post_send_image(contact.phone, image_url, '')
                response = _post_send_text(contact.phone, message)
                response['image_response'] = image_response.get('response')
                mode = 'image_then_text'
            else:
                response = _post_send_text(contact.phone, message)
                mode = 'text_only'
            existing.status = 'sent'
            existing.sent_at = datetime.utcnow()
            existing.provider_message_id = response.get('message_id', '')
            existing.response_body = serialize_payload({'provider': 'baileys', 'mode': mode, 'response': response.get('response')})
            existing.error_message = ''
            results.append({'contact': contact, 'status': 'sent'})
            processed += 1
            db.session.commit()
            if batch_size is not None and processed >= batch_size:
                break
            time.sleep(delay)
        except Exception as exc:
            existing.status = 'error'; existing.error_message = str(exc); existing.response_body = ''
            db.session.commit()
            results.append({'contact': contact, 'status': 'error', 'reason': str(exc)})
    return results
