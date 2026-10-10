import hmac
import secrets
from flask import session, request, abort


def panel_csrf():
    return session.setdefault('panel_csrf', secrets.token_urlsafe(32))


def check_panel_csrf():
    expected = session.get('panel_csrf', '')
    if not expected or not hmac.compare_digest(expected, request.form.get('csrf_token', '')):
        abort(400, description='Formulário expirado. Atualize a página e tente novamente.')
