from random import shuffle
import hmac
import re
import secrets
from urllib.parse import quote_plus
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session
from app import db
from app.models import SiteSettings, GuestbookMessage, GiftItem, GiftPurchase, ContactLead, Ceremony, FAQ
from app.services.message_ai import generate_loving_message
from app.services.mercado_pago import MercadoPagoService
from app.services.whatsapp import normalize_whatsapp_phone
from app.services.payment_status import apply_verified_payment
from app.utils import format_phone
from app.services.contact_import import contact_write_lock
from app.services.invitations import record_invitation_response, selected_invitation_names

public_bp = Blueprint('public', __name__)


def _location_query(settings):
    parts = []
    if settings:
        parts = [
            getattr(settings, 'wedding_location_name', '') or '',
            getattr(settings, 'wedding_address', '') or '',
            getattr(settings, 'wedding_city', '') or '',
        ]
    return ' ,'.join([part.strip() for part in parts if part and part.strip()]).replace(' ,', ' , ')


def _map_embed_url(settings):
    if settings and settings.map_embed_url:
        return settings.map_embed_url
    query = _location_query(settings)
    if not query:
        return ''
    return f"https://maps.google.com/maps?q={quote_plus(query)}&t=&z=15&ie=UTF8&iwloc=&output=embed"


def _route_url(settings):
    if settings and settings.route_url:
        return settings.route_url
    query = _location_query(settings)
    if not query:
        return ''
    return f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(query)}"


def _guestbook_cards(messages):
    cards = []
    for item in messages:
        raw_name = (item.author_name or '').strip()
        parts = [part for part in raw_name.split() if part]
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[1][0]).upper()
        elif parts:
            initials = parts[0][:2].upper()
        else:
            initials = '??'
        cards.append({
            'item': item,
            'initials': initials,
            'posted_at': item.created_at.strftime('%d/%m/%Y') if item.created_at else '',
        })
    return cards


@public_bp.route('/')
def home():
    if 'codigo' in request.args:
        return _open_invitation(request.args.get('codigo', ''))
    settings = SiteSettings.query.first()
    guestbook_messages = GuestbookMessage.query.filter_by(approved=True).order_by(GuestbookMessage.created_at.desc()).limit(8).all()
    gifts = GiftItem.query.filter_by(active=True).order_by(GiftItem.created_at.desc()).limit(6).all()
    countdown_target = settings.wedding_date.isoformat() if settings and settings.wedding_date else ''
    return render_template(
        'public/home.html',
        settings=settings,
        guestbook_messages=_guestbook_cards(guestbook_messages),
        gifts=gifts,
        countdown_target=countdown_target,
        ceremonies=Ceremony.query.order_by(Ceremony.id).all(),
        faqs=FAQ.query.filter_by(active=True).order_by(FAQ.position, FAQ.id).all(),
        computed_map_embed_url=_map_embed_url(settings),
        computed_route_url=_route_url(settings),
    )


def _invitation_contact(code, lock=False):
    code = str(code or '').strip()
    if not re.fullmatch(r'[0-9]{4,20}', code):
        return None
    query = ContactLead.query.filter_by(confirmation_code=code)
    if lock:
        query = query.populate_existing().with_for_update()
    matches = query.limit(2).all()
    return matches[0] if len(matches) == 1 else None


def _open_invitation(code):
    contact = _invitation_contact(code)
    session.pop('rsvp_code', None)
    if contact:
        session['rsvp_code'] = contact.confirmation_code
    else:
        flash('Não encontramos esse convite. Confira o código recebido pelo WhatsApp e tente novamente.', 'warning')
    # Remove the credential from the URL before rendering any external assets.
    return redirect(url_for('public.rsvp'), code=303)


@public_bp.after_request
def protect_invitation_response(response):
    if request.endpoint == 'public.rsvp' or (request.endpoint == 'public.home' and 'codigo' in request.args):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@public_bp.route('/confirmar-presenca', methods=['GET', 'POST'])
@public_bp.route('/rsvp', methods=['GET', 'POST'])
def rsvp():
    if request.method == 'GET' and 'codigo' in request.args:
        return _open_invitation(request.args.get('codigo', ''))
    csrf_token = session.setdefault('rsvp_csrf', secrets.token_urlsafe(32))
    if request.method == 'POST':
        received = request.form.get('csrf_token', '')
        if not received or not hmac.compare_digest(csrf_token.encode(), received.encode()):
            flash('Esta página expirou. Confira o convite abaixo e tente novamente.', 'warning')
            return redirect(url_for('public.rsvp'), code=303)
        action = request.form.get('action', '')
        if action == 'lookup':
            return _open_invitation(request.form.get('confirmation_code', ''))
        if action == 'clear':
            session.pop('rsvp_code', None)
            return redirect(url_for('public.rsvp'), code=303)
        attendance = request.form.get('attendance', '')
        message = request.form.get('message', '').strip()
        if action != 'reply' or attendance not in ('yes', 'no') or len(message) > 3000:
            flash('Escolha confirmar ou recusar a presença. O recado pode ter até 3.000 caracteres.', 'warning')
            return redirect(url_for('public.rsvp'), code=303)
        with contact_write_lock():
            contact = _invitation_contact(session.get('rsvp_code'), lock=True)
            if not contact:
                session.pop('rsvp_code', None)
                flash('Confira o código recebido pelo WhatsApp para identificar seu convite.', 'warning')
            elif not contact.people_count:
                flash('Precisamos conferir os nomes deste convite. Entre em contato com o casal.', 'warning')
            else:
                # The shared transaction lock serializes clicks and concurrent devices.
                previous = contact.latest_rsvp
                new_reply = not previous or not previous.confirmed_at
                try:
                    selected = selected_invitation_names(contact, request.form, attendance)
                except ValueError as exc:
                    flash(str(exc), 'warning')
                else:
                    record_invitation_response(contact, attendance, message, selected_names=selected)
                    db.session.commit()
                    if attendance == 'yes' and new_reply:
                        session['rsvp_gift_transition'] = True
        return redirect(url_for('public.rsvp'), code=303)
    contact = _invitation_contact(session.get('rsvp_code'))
    if not contact:
        session.pop('rsvp_code', None)
    return render_template('public/rsvp.html', invitation=contact,
                           response=contact.latest_rsvp if contact else None, csrf_token=csrf_token,
                           gift_transition=session.pop('rsvp_gift_transition', False))


@public_bp.route('/mural')
def guestbook():
    pagination = GuestbookMessage.query.filter_by(approved=True).order_by(GuestbookMessage.created_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=24, error_out=False)
    return render_template('public/guestbook.html', messages=_guestbook_cards(pagination.items), pagination=pagination)


@public_bp.route('/presentes')
def gifts():
    gifts = GiftItem.query.filter_by(active=True).all()
    shuffle(gifts)
    return render_template('public/gifts.html', gifts=gifts)


@public_bp.route('/presentes/<int:gift_id>/checkout', methods=['GET', 'POST'])
def gift_checkout(gift_id):
    gift = GiftItem.query.get_or_404(gift_id)
    settings = SiteSettings.query.first()

    if not gift.is_available:
        flash('Este presente não está mais disponível.', 'warning')
        return redirect(url_for('public.gifts'))

    if request.method == 'POST':
        name = request.form.get('buyer_name', '').strip()
        email = request.form.get('buyer_email', '').strip()
        phone = format_phone(request.form.get('buyer_phone', '').strip())
        message = request.form.get('message', '').strip()
        if not name or len(name) > 180 or not email or '@' not in email or len(email) > 120 or not phone or len(phone) > 40 or len(message) > 3000:
            flash('Confira seus dados. O recado deve ter até 3.000 caracteres.', 'danger')
            return redirect(url_for('public.gift_checkout', gift_id=gift.id))
        purchase = GiftPurchase(
            gift_id=gift.id,
            buyer_name=request.form.get('buyer_name', '').strip(),
            buyer_email=request.form.get('buyer_email', '').strip(),
            buyer_phone=format_phone(request.form.get('buyer_phone', '').strip()),
            confirmed_presence=request.form.get('confirmed_presence') == 'on',
            message=request.form.get('message', '').strip(),
            amount=gift.price,
            status='pending',
        )
        db.session.add(purchase)
        db.session.commit()

        pref = MercadoPagoService.create_preference(
            purchase=purchase,
            gift_title=gift.title,
            success_url=url_for('public.checkout_result', status='success', _external=True),
            pending_url=url_for('public.checkout_result', status='pending', _external=True),
            failure_url=url_for('public.checkout_result', status='failure', _external=True),
            notification_url=url_for('api.mercado_pago_webhook', _external=True),
        )

        if pref.get('reference'):
            purchase.mercado_pago_preference_id = pref['reference']
            db.session.commit()

        if pref.get('enabled') and pref.get('sandbox_url'):
            return redirect(pref['sandbox_url'])

        flash(pref.get('message') or 'Checkout indisponível no momento.', pref.get('category', 'warning'))
        return redirect(url_for('public.checkout_result', status='pending'))

    initial_message = generate_loving_message(settings.couple_names if settings else 'Kemily & Pedro')
    return render_template('public/checkout.html', gift=gift, initial_message=initial_message)


@public_bp.route('/checkout/<status>')
def checkout_result(status):
    payment_id = request.args.get('payment_id') or request.args.get('collection_id')
    reported_status = request.args.get('status') or request.args.get('collection_status')
    resolved = 'pending'
    verified = False
    payment_method = ''
    if payment_id:
        try:
            payment = MercadoPagoService.fetch_payment(payment_id)
            # Query parameters never approve a purchase or select its reference.
            if str(payment.get('id') or '') == str(payment_id):
                purchase = apply_verified_payment(payment)
                if purchase:
                    db.session.commit()
                    verified = True
                    payment_method = payment.get('payment_method_id', '')
                    resolved = 'success' if purchase.status == 'approved' else ('pending' if purchase.status in ('pending','in_process','authorized','in_mediation') else 'failure')
        except Exception:
            db.session.rollback()
            current_app.logger.warning('Não foi possível verificar retorno do pagamento %s', str(payment_id)[:30])
    # A failed return can show a retry message, but a success path alone proves nothing.
    if not verified and (status == 'failure' or reported_status in ('rejected','cancelled','refunded','charged_back')):
        resolved = 'failure'
    boleto = payment_method in ('bolbradesco','pec','boleto') or (not verified and request.args.get('payment_type') == 'ticket')
    return render_template('public/checkout_result.html', status=resolved, verified=verified, boleto=boleto)


@public_bp.route('/gerar-mensagem')
def generate_message():
    settings = SiteSettings.query.first()
    return jsonify({'message': generate_loving_message(settings.couple_names if settings else 'Kemily & Pedro')})
