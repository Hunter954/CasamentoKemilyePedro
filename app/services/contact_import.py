"""Shared contact validation and atomic, idempotent WhatsApp imports."""
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import text

from app import db
from app.models import ContactLead, ContactImportSettings, ContactImportEvent
from app.services.whatsapp import get_or_create_contact_code

_contact_lock = threading.RLock()


def clean_phone(value):
    raw = str(value or '').strip()
    digits = re.sub(r'[^0-9]', '', raw)
    international = raw.startswith(('+', '00'))
    if digits.startswith('00'):
        digits = digits[2:]
    if not international and len(digits) in (10, 11):
        digits = '55' + digits
    elif not international and not (digits.startswith('55') and len(digits) in (12, 13)):
        return ''
    if digits.startswith('55'):
        if len(digits) not in (12, 13) or digits[2] == '0' or digits[4] == '0':
            return ''
    elif not 8 <= len(digits) <= 15 or digits.startswith('0'):
        return ''
    return digits if digits.startswith('55') else '+' + digits


def phone_key(value):
    phone = clean_phone(value)
    # Old Brazilian mobile numbers and their ninth-digit equivalents are the
    # same guest. Landlines keep their eight-digit subscriber number.
    if phone.startswith('55') and len(phone) == 12 and phone[4] in '6789':
        phone = phone[:4] + '9' + phone[4:]
    return phone.lstrip('+')


@contextmanager
def contact_write_lock():
    # Shared by manual edits, deletion and imports. PostgreSQL coordinates every
    # worker/container; the process lock also covers the SQLite development DB.
    with _contact_lock:
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text('SELECT pg_advisory_xact_lock(74201951)'))
            yield
        except Exception:
            db.session.rollback()
            raise


def import_settings():
    settings = db.session.get(ContactImportSettings, 1)
    if settings is None:
        settings = ContactImportSettings(id=1, enabled=False)
        db.session.add(settings)
        db.session.flush()
    return settings


def find_duplicate(phone, exclude_id=None):
    key = phone_key(phone)
    if not key:
        return None
    return next((item for item in ContactLead.query.order_by(ContactLead.id).all()
                 if item.id != exclude_id and phone_key(item.phone) == key), None)


def import_contacts(payload):
    if not isinstance(payload, dict):
        raise ValueError('Formato inválido.')
    group = str(payload.get('groupJid') or '')
    message_id = str(payload.get('messageId') or '')
    contacts = payload.get('contacts')
    if not group.endswith('@g.us') or not message_id or len(message_id) > 200:
        raise ValueError('Mensagem ou grupo inválido.')
    if not isinstance(contacts, list) or not 1 <= len(contacts) <= 100:
        raise ValueError('Envie de 1 a 100 contatos por lote.')
    try:
        received_at = datetime.utcfromtimestamp(float(payload['timestamp']))
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ValueError('Data da mensagem inválida.')
    event_key = hashlib.sha256(f'{group}:{message_id}'.encode()).hexdigest()
    with contact_write_lock():
        settings = import_settings()
        if (not settings.enabled or group != settings.group_jid or not settings.activated_at
                or received_at < settings.activated_at.replace(microsecond=0)):
            db.session.commit()
            return {'ok': True, 'ignored': True}
        existing = db.session.get(ContactImportEvent, event_key)
        if existing:
            db.session.commit()
            return {'ok': True, 'replayed': True, 'created': existing.created_count,
                    'duplicates': existing.duplicate_count, 'invalid': existing.invalid_count}
        event = ContactImportEvent(event_key=event_key, group_name=settings.group_name,
                                   sender_name=str(payload.get('senderName') or 'Participante do grupo')[:180],
                                   created_count=0, duplicate_count=0, invalid_count=0)
        db.session.add(event)
        known = {phone_key(item.phone): item for item in ContactLead.query.order_by(ContactLead.id).all()}
        details = []
        for card in contacts:
            card = card if isinstance(card, dict) else {}
            name = re.sub(r'\s+', ' ', str(card.get('name') or '')).strip()[:180]
            phone = clean_phone(card.get('phone'))
            key = phone_key(phone)
            if not name or not phone:
                event.invalid_count += 1
                details.append({'name': name or 'Contato sem nome', 'status': 'invalid'})
                continue
            if key in known:
                event.duplicate_count += 1
                details.append({'name': name, 'status': 'duplicate', 'contact_id': known[key].id})
                continue
            contact = ContactLead(name=name, phone=phone, tag='convidado', email='')
            db.session.add(contact)
            db.session.flush()
            get_or_create_contact_code(contact)
            known[key] = contact
            event.created_count += 1
            details.append({'name': name, 'status': 'created', 'contact_id': contact.id})
        event.details = json.dumps(details, ensure_ascii=False)
        db.session.commit()
        return {'ok': True, 'created': event.created_count, 'duplicates': event.duplicate_count,
                'invalid': event.invalid_count}


def import_overview():
    settings = import_settings()
    totals = db.session.query(db.func.coalesce(db.func.sum(ContactImportEvent.created_count), 0),
                              db.func.coalesce(db.func.sum(ContactImportEvent.duplicate_count), 0),
                              db.func.coalesce(db.func.sum(ContactImportEvent.invalid_count), 0)).one()
    events = ContactImportEvent.query.order_by(ContactImportEvent.created_at.desc()).limit(8).all()
    return {'enabled': settings.enabled, 'group_name': settings.group_name,
            'created': totals[0], 'duplicates': totals[1], 'invalid': totals[2],
            'total': ContactLead.query.count(),
            'latest': events[0].event_key if events else '',
            'events': [{'sender': event.sender_name, 'group': event.group_name,
                        'at': event.created_at.isoformat() + 'Z', 'created': event.created_count,
                        'duplicates': event.duplicate_count, 'invalid': event.invalid_count,
                        'details': json.loads(event.details)} for event in events]}
