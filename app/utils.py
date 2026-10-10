from datetime import datetime
from pathlib import Path
from uuid import uuid4
from flask import current_app
from werkzeug.utils import secure_filename


def format_currency(value):
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    return f'R$ {numeric:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def normalize_phone_digits(value, default_country_code='55'):
    digits = ''.join(char for char in str(value or '') if char.isdigit())
    if not digits:
        return ''
    if default_country_code and not digits.startswith(default_country_code) and len(digits) in {10, 11}:
        return f'{default_country_code}{digits}'
    return digits


def format_phone(value):
    raw = str(value or '').strip()
    digits = ''.join(char for char in str(value or '') if char.isdigit())
    if raw.startswith('+') and not digits.startswith('55'):
        return raw
    if digits.startswith('55') and len(digits) in (12, 13):
        return '+55 ' + format_phone(digits[2:])
    if len(digits) == 11:
        return f'({digits[:2]}) {digits[2:7]}-{digits[7:]}'
    if len(digits) == 10:
        return f'({digits[:2]}) {digits[2:6]}-{digits[6:]}'
    if len(digits) > 11:
        country = digits[:-11]
        local = digits[-11:]
        if len(local) == 11:
            return f'+{country} ({local[:2]}) {local[2:7]}-{local[7:]}'
        if len(local) == 10:
            return f'+{country} ({local[:2]}) {local[2:6]}-{local[6:]}'
    return str(value or '').strip()


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return ''
    extension = Path(secure_filename(file_storage.filename)).suffix
    filename = f'{uuid4().hex}{extension}'
    destination = Path(current_app.config['UPLOAD_DIR']) / filename
    file_storage.save(destination)
    return f'uploads/{filename}'


def to_public_media_url(file_path, site_url=''):
    if not file_path:
        return ''
    raw = str(file_path).strip()
    if raw.startswith(('http://', 'https://')):
        return raw
    filename = raw.split('/')[-1]
    base = (site_url or '').strip().rstrip('/')
    if not base:
        return f'/media/{filename}'
    return f'{base}/media/{filename}'


def parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
