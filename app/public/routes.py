from datetime import datetime
from urllib.parse import quote_plus
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import SiteSettings, GuestbookMessage, RSVP, GiftItem, GiftPurchase, ContactLead, Ceremony, FAQ
from app.services.message_ai import generate_loving_message
from app.services.mercado_pago import MercadoPagoService
from app.services.whatsapp import normalize_whatsapp_phone
from app.utils import format_phone

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


@public_bp.route('/confirmar-presenca', methods=['GET', 'POST'])
@public_bp.route('/rsvp', methods=['GET', 'POST'])
def rsvp():
    if request.method == 'POST':
        code = ''.join(char for char in request.form.get('confirmation_code', '') if char.isdigit())
        if not code:
            flash('Digite o código que você recebeu no WhatsApp.', 'danger')
            return redirect(url_for('public.rsvp'))

        contact = ContactLead.query.filter_by(confirmation_code=code).first()
        if not contact:
            flash('Código não encontrado. Confira o número enviado no WhatsApp e tente novamente.', 'danger')
            return redirect(url_for('public.rsvp'))

        existing = RSVP.query.filter_by(contact_id=contact.id).order_by(RSVP.created_at.desc()).first()
        if existing and existing.confirmed_at:
            flash('Este código já foi confirmado anteriormente.', 'warning')
            return redirect(url_for('public.rsvp'))

        attendance = request.form.get('attendance', 'yes')
        if attendance not in ('yes', 'no'):
            flash('Selecione se você irá comparecer.', 'danger')
            return redirect(url_for('public.rsvp'))
        try:
            guests_count = int(request.form.get('guests_count', 1) or 1) if attendance == 'yes' else 0
            if attendance == 'yes' and not 1 <= guests_count <= 10:
                raise ValueError()
        except (TypeError, ValueError):
            flash('Informe uma quantidade de 1 a 10 pessoas.', 'danger')
            return redirect(url_for('public.rsvp'))
        message = request.form.get('message', '').strip()

        if existing:
            existing.guest_name = contact.name
            existing.phone = format_phone(contact.phone)
            existing.guests_count = guests_count
            existing.attendance = attendance
            existing.message = message
            existing.confirmation_code = code
            existing.confirmed_at = datetime.utcnow()
            existing.email = existing.email or (contact.email or '').strip()
        else:
            existing = RSVP(
                guest_name=contact.name,
                phone=format_phone(contact.phone),
                email=(contact.email or '').strip(),
                guests_count=guests_count,
                attendance=attendance,
                message=message,
                contact_id=contact.id,
                confirmation_code=code,
                confirmed_at=datetime.utcnow(),
            )
            db.session.add(existing)

        db.session.commit()
        flash(f'Presença registrada com sucesso para {contact.name}. Obrigado!', 'success')
        return redirect(url_for('public.rsvp'))
    return render_template('public/rsvp.html')


@public_bp.route('/mural', methods=['GET', 'POST'])
def guestbook():
    settings = SiteSettings.query.first()
    if request.method == 'POST':
        if settings and not settings.allow_guestbook:
            flash('O mural está temporariamente desativado.', 'warning')
            return redirect(url_for('public.guestbook'))
        author = request.form.get('author_name', '').strip()
        content = request.form.get('message', '').strip()
        if not author or len(author) > 120 or not content or len(content) > 3000:
            flash('Informe seu nome (até 120 caracteres) e um recado (até 3.000 caracteres).', 'danger')
            return redirect(url_for('public.guestbook'))
        message = GuestbookMessage(
            author_name=author,
            message=content,
            approved=not (settings.require_guestbook_approval if settings else True),
        )
        db.session.add(message)
        db.session.commit()
        flash('Recado enviado! Ele aparecerá após aprovação.' if (settings.require_guestbook_approval if settings else True) else 'Recado publicado com sucesso!', 'success')
        return redirect(url_for('public.guestbook'))
    pagination = GuestbookMessage.query.filter_by(approved=True).order_by(GuestbookMessage.created_at.desc()).paginate(page=request.args.get('page', 1, type=int), per_page=24, error_out=False)
    return render_template('public/guestbook.html', messages=_guestbook_cards(pagination.items), pagination=pagination)


@public_bp.route('/presentes')
def gifts():
    gifts = GiftItem.query.filter_by(active=True).order_by(GiftItem.price.asc()).all()
    return render_template('public/gifts.html', gifts=gifts)


@public_bp.route('/presentes/<int:gift_id>/checkout', methods=['GET', 'POST'])
def gift_checkout(gift_id):
    gift = GiftItem.query.get_or_404(gift_id)
    settings = SiteSettings.query.first()

    if not gift.is_available:
        flash('Este presente não está mais disponível.', 'warning')
        return redirect(url_for('public.gifts'))

    if request.method == 'POST':
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
    return render_template('public/checkout_result.html', status=status)


@public_bp.route('/gerar-mensagem')
def generate_message():
    settings = SiteSettings.query.first()
    return jsonify({'message': generate_loving_message(settings.couple_names if settings else 'Kemily & Pedro')})
