import hmac
import secrets
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.models import (
    AdminUser,
    SiteSettings,
    RSVP,
    GuestbookMessage,
    GiftItem,
    GiftPurchase,
    ContactLead,
    WhatsAppCampaign,
    WhatsAppDispatch,
    WhatsAppWebhookLog,
)
from app.utils import save_upload, parse_datetime, format_phone, normalize_phone_digits
from app.services.whatsapp import (
    send_campaign_messages,
    send_test_message,
    WhatsAppConfigError,
    get_or_create_contact_code,
    ensure_all_contact_codes,
    get_queue_count,
    get_queue_snapshot,
    get_instance_status,
    get_instance_data,
    get_qrcode_image_base64,
    restart_instance,
    disconnect_instance,
    configure_instance_webhooks,
    _bridge_request,
)
from app.services.contact_import import (clean_phone, contact_write_lock, find_duplicate,
                                         import_settings, import_overview)

admin_bp = Blueprint('admin', __name__)


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _tag_options():
    tags = [tag for (tag,) in db.session.query(ContactLead.tag).distinct().order_by(ContactLead.tag.asc()).all() if tag]
    return ['todos'] + tags


@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        # Não aplicar strip na senha: espaços podem fazer parte legitimamente dela.
        password = request.form.get('password', '')
        user = AdminUser.query.filter(db.func.lower(AdminUser.email) == email).first()
        if user and user.is_active and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin.dashboard'))
        flash('Credenciais inválidas.', 'danger')
    return render_template('admin/login.html')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sessão encerrada com sucesso.', 'success')
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@login_required
def dashboard():
    approved_purchases = GiftPurchase.query.filter_by(status='approved')
    stats = {
        'rsvps': RSVP.query.count(),
        'approved_messages': GuestbookMessage.query.filter_by(approved=True).count(),
        'gifts': GiftItem.query.count(),
        'paid': approved_purchases.count(),
        'paid_total': sum(item.amount or 0 for item in approved_purchases.all()),
        'contacts': ContactLead.query.count(),
        'campaigns': WhatsAppCampaign.query.count(),
        'dispatches_sent': WhatsAppDispatch.query.filter_by(status='sent').count(),
    }
    purchases = GiftPurchase.query.order_by(GiftPurchase.created_at.desc()).limit(8).all()
    return render_template('admin/dashboard.html', stats=stats, purchases=purchases)


@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def settings():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
        db.session.commit()
    if request.method == 'POST':
        settings.couple_names = request.form.get('couple_names', '')
        settings.hero_phrase = request.form.get('hero_phrase', '')
        settings.wedding_date = parse_datetime(request.form.get('wedding_date', ''))
        settings.wedding_location_name = request.form.get('wedding_location_name', '')
        settings.wedding_address = request.form.get('wedding_address', '')
        settings.wedding_city = request.form.get('wedding_city', '')
        settings.wedding_time = request.form.get('wedding_time', '')
        settings.map_embed_url = request.form.get('map_embed_url', '')
        settings.route_url = request.form.get('route_url', '')
        settings.gift_banner_title = request.form.get('gift_banner_title', '')
        settings.gift_button_label = request.form.get('gift_button_label', '')
        settings.final_message = request.form.get('final_message', '')
        settings.theme_primary = request.form.get('theme_primary', '#7a3144')
        settings.theme_secondary = request.form.get('theme_secondary', '#f7d7df')
        settings.theme_accent = request.form.get('theme_accent', '#f14d78')
        settings.allow_guestbook = request.form.get('allow_guestbook') == 'on'
        settings.require_guestbook_approval = request.form.get('require_guestbook_approval') == 'on'
        settings.whatsapp_message_template = request.form.get('whatsapp_message_template', '')
        settings.mercado_pago_enabled = request.form.get('mercado_pago_enabled') == 'on'
        settings.mercado_pago_access_token = request.form.get('mercado_pago_access_token', '').strip()
        settings.mercado_pago_public_key = request.form.get('mercado_pago_public_key', '').strip()

        hero_upload = request.files.get('hero_image')
        gift_banner_upload = request.files.get('gift_banner_image')
        if hero_upload and hero_upload.filename:
            settings.hero_image = save_upload(hero_upload)
        if gift_banner_upload and gift_banner_upload.filename:
            settings.gift_banner_image = save_upload(gift_banner_upload)

        db.session.commit()
        flash('Configurações salvas com sucesso.', 'success')
        return redirect(url_for('admin.settings'))
    return render_template('admin/settings.html', settings=settings)


@admin_bp.route('/configuracoes/whatsapp/testar', methods=['POST'])
@login_required
def test_whatsapp():
    phone = request.form.get('test_phone', '').strip()
    message = request.form.get('test_message', '').strip() or 'Teste do WhatsApp enviado pelo painel do casamento.'
    try:
        send_test_message(phone=phone, message=message)
        flash('Mensagem de teste enviada com sucesso.', 'success')
    except Exception as exc:
        flash(f'Falha no teste do WhatsApp: {exc}', 'danger')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/presentes', methods=['GET', 'POST'])
@login_required
def manage_gifts():
    edit_id = request.args.get('edit', type=int)
    edit_gift = GiftItem.query.get(edit_id) if edit_id else None

    if request.method == 'POST':
        image_upload = request.files.get('image')
        image_path = save_upload(image_upload) if image_upload and image_upload.filename else ''
        item = GiftItem(
            title=request.form.get('title', '').strip(),
            description=request.form.get('description', '').strip(),
            price=_to_float((request.form.get('price', '') or '').replace('.', '').replace(',', '.')),
            image_url=image_path,
            active=request.form.get('active') == 'on',
            allow_multiple_purchases=request.form.get('allow_multiple_purchases') == 'on',
        )
        db.session.add(item)
        db.session.commit()
        flash('Presente cadastrado com sucesso.', 'success')
        return redirect(url_for('admin.manage_gifts'))

    gifts = GiftItem.query.order_by(GiftItem.created_at.desc()).all()
    return render_template('admin/gifts.html', gifts=gifts, edit_gift=edit_gift)


@admin_bp.route('/presentes/<int:gift_id>/toggle', methods=['POST'])
@login_required
def toggle_gift(gift_id):
    gift = GiftItem.query.get_or_404(gift_id)
    gift.active = not gift.active
    db.session.commit()
    flash(f'Presente {"ativado" if gift.active else "desativado"} com sucesso.', 'success')
    return redirect(url_for('admin.manage_gifts'))


@admin_bp.route('/presentes/<int:gift_id>/editar', methods=['POST'])
@login_required
def edit_gift(gift_id):
    gift = GiftItem.query.get_or_404(gift_id)
    gift.title = request.form.get('title', gift.title)
    gift.description = request.form.get('description', gift.description)
    gift.price = _to_float((request.form.get('price', gift.price) or '').replace('.', '').replace(',', '.'))
    gift.active = request.form.get('active') == 'on'
    gift.allow_multiple_purchases = request.form.get('allow_multiple_purchases') == 'on'
    image_upload = request.files.get('image')
    if image_upload and image_upload.filename:
        gift.image_url = save_upload(image_upload)
    db.session.commit()
    flash('Presente atualizado com sucesso.', 'success')
    return redirect(url_for('admin.manage_gifts'))


@admin_bp.route('/presentes/<int:gift_id>/excluir', methods=['POST'])
@login_required
def delete_gift(gift_id):
    gift = GiftItem.query.get_or_404(gift_id)
    db.session.delete(gift)
    db.session.commit()
    flash('Presente excluído.', 'success')
    return redirect(url_for('admin.manage_gifts'))


@admin_bp.route('/confirmacoes')
@login_required
def manage_rsvps():
    ensure_all_contact_codes(commit=True)
    contacts = ContactLead.query.order_by(ContactLead.created_at.desc()).all()
    rows = []
    for contact in contacts:
        latest_rsvp = RSVP.query.filter_by(contact_id=contact.id).order_by(RSVP.created_at.desc()).first()
        rows.append({
            'contact': contact,
            'rsvp': latest_rsvp,
            'confirmed': bool(latest_rsvp and latest_rsvp.confirmed_at),
        })
    legacy_rsvps = RSVP.query.filter(RSVP.contact_id.is_(None)).order_by(RSVP.created_at.desc()).all()
    return render_template('admin/rsvps.html', rows=rows, legacy_rsvps=legacy_rsvps)


@admin_bp.route('/mural')
@login_required
def manage_guestbook():
    messages = GuestbookMessage.query.order_by(GuestbookMessage.created_at.desc()).all()
    return render_template('admin/guestbook.html', messages=messages)


@admin_bp.route('/mural/<int:message_id>/aprovar')
@login_required
def approve_message(message_id):
    message = GuestbookMessage.query.get_or_404(message_id)
    message.approved = True
    db.session.commit()
    flash('Recado aprovado.', 'success')
    return redirect(url_for('admin.manage_guestbook'))


@admin_bp.route('/mural/<int:message_id>/desaprovar')
@login_required
def disapprove_message(message_id):
    message = GuestbookMessage.query.get_or_404(message_id)
    message.approved = False
    db.session.commit()
    flash('Recado movido para pendente.', 'success')
    return redirect(url_for('admin.manage_guestbook'))


@admin_bp.route('/mural/<int:message_id>/excluir', methods=['POST'])
@login_required
def delete_message(message_id):
    message = GuestbookMessage.query.get_or_404(message_id)
    db.session.delete(message)
    db.session.commit()
    flash('Recado excluído.', 'success')
    return redirect(url_for('admin.manage_guestbook'))


@admin_bp.route('/compras')
@login_required
def purchases():
    purchases = GiftPurchase.query.order_by(GiftPurchase.created_at.desc()).all()
    return render_template('admin/purchases.html', purchases=purchases)


@admin_bp.route('/compras/<int:purchase_id>/excluir', methods=['POST'])
@login_required
def delete_purchase(purchase_id):
    purchase = GiftPurchase.query.get_or_404(purchase_id)
    db.session.delete(purchase)
    db.session.commit()
    flash('Compra excluída com sucesso.', 'success')
    return redirect(url_for('admin.purchases'))


@admin_bp.route('/contatos', methods=['GET', 'POST'])
@login_required
def contacts():
    edit_id = request.args.get('edit', type=int)
    editing_contact = ContactLead.query.get(edit_id) if edit_id else None
    status_code = 200
    csrf_token = session.setdefault('contacts_csrf', secrets.token_urlsafe(32))
    if request.method == 'POST':
        _check_contacts_csrf()
        contact_id = request.form.get('contact_id', type=int)
        editing_contact = ContactLead.query.get_or_404(contact_id) if contact_id else None
        phone = clean_phone(request.form.get('phone', ''))
        name = request.form.get('name', '').strip()[:180]
        tag = request.form.get('tag', 'convidado').strip()[:80] or 'convidado'
        if not name or not phone:
            flash('Informe o nome e um telefone válido com DDD. Para outros países, use + e o código do país.', 'danger')
            status_code = 422
        else:
            with contact_write_lock():
                duplicate = find_duplicate(phone, exclude_id=contact_id)
                if duplicate:
                    flash(f'Este telefone já pertence a {duplicate.name}. O cadastro existente foi mantido.', 'warning')
                    duplicate_id = duplicate.id
                    db.session.commit()
                    return redirect(url_for('admin.contacts', edit=duplicate_id))
                contact = editing_contact or ContactLead(email='')
                contact.name, contact.phone, contact.tag = name, phone, tag
                db.session.add(contact)
                db.session.flush()
                get_or_create_contact_code(contact)
                db.session.commit()
            flash('Convidado atualizado.' if contact_id else 'Convidado cadastrado. O código de confirmação já está pronto.', 'success')
            return redirect(url_for('admin.contacts'))

    with contact_write_lock():
        ensure_all_contact_codes()
        overview = import_overview()
        settings = import_settings()
        db.session.commit()
    query = ContactLead.query
    search = request.args.get('q', '').strip()[:180]
    tag = request.args.get('tag', '').strip()[:80]
    if search:
        phone_search = ''.join(char for char in search if char.isdigit())
        phone_column = ContactLead.phone
        for character in (' ', '(', ')', '-', '+'):
            phone_column = db.func.replace(phone_column, character, '')
        filters = [db.func.lower(ContactLead.name).contains(search.lower(), autoescape=True),
                   ContactLead.confirmation_code.contains(search, autoescape=True)]
        if phone_search:
            filters.append(phone_column.contains(phone_search, autoescape=True))
        query = query.filter(db.or_(*filters))
    if tag:
        query = query.filter(ContactLead.tag == tag)
    pagination = query.order_by(ContactLead.created_at.desc(), ContactLead.id.desc()).paginate(
        page=max(1, request.args.get('page', 1, type=int)), per_page=25, error_out=False)
    form_data = request.form if request.method == 'POST' else {
        'name': editing_contact.name if editing_contact else '',
        'phone': editing_contact.phone if editing_contact else '',
        'tag': editing_contact.tag if editing_contact else 'convidado'}
    return render_template('admin/contacts.html', contacts=pagination.items, pagination=pagination,
                           editing_contact=editing_contact, form_data=form_data, csrf_token=csrf_token,
                           import_settings=settings, overview=overview, search=search, tag=tag,
                           tags=_tag_options()[1:]), status_code


def _check_contacts_csrf():
    expected = session.get('contacts_csrf', '')
    received = request.form.get('csrf_token', '')
    if not expected or not hmac.compare_digest(expected.encode(), received.encode()):
        abort(400, description='Atualize a página e tente novamente.')


@admin_bp.route('/contatos/whatsapp/grupos')
@login_required
def contact_import_groups():
    try:
        return jsonify(_bridge_request('GET', '/groups', timeout=20))
    except Exception:
        return jsonify({'error': 'Não foi possível carregar os grupos. Confira a conexão do WhatsApp e tente novamente.'}), 503


@admin_bp.route('/contatos/whatsapp/configurar', methods=['POST'])
@login_required
def configure_contact_import():
    _check_contacts_csrf()
    if request.form.get('action') == 'pause':
        with contact_write_lock():
            import_settings().enabled = False
            db.session.commit()
        flash('Importação pausada. Os convidados cadastrados foram mantidos.', 'success')
        return redirect(url_for('admin.contacts'))
    group_jid = request.form.get('group_jid', '')
    try:
        groups = _bridge_request('GET', '/groups', timeout=20).get('groups', [])
        group = next((item for item in groups if item.get('id') == group_jid), None)
        if not group:
            flash('Escolha um dos grupos disponíveis no WhatsApp conectado.', 'danger')
            return redirect(url_for('admin.contacts'))
        with contact_write_lock():
            settings = import_settings()
            # Saving the same active group preserves queued offline contacts.
            if not settings.enabled or settings.group_jid != group_jid:
                settings.activated_at = datetime.utcnow()
            settings.group_jid = group_jid
            settings.group_name = str(group.get('name') or 'Convidados')[:180]
            settings.enabled = True
            db.session.commit()
        flash('Importação ativada! Encaminhe os contatos no grupo escolhido para cadastrar os convidados.', 'success')
    except Exception:
        db.session.rollback()
        flash('Não foi possível ativar. Confira a conexão do WhatsApp e tente novamente.', 'danger')
    return redirect(url_for('admin.contacts'))


@admin_bp.route('/contatos/whatsapp/status')
@login_required
def contact_import_status():
    with contact_write_lock():
        overview = import_overview()
        db.session.commit()
    try:
        overview['bridge'] = _bridge_request('GET', '/contacts/status', timeout=3)
    except Exception:
        overview['bridge'] = {'ready': False, 'unavailable': True}
    return jsonify(overview)


@admin_bp.route('/contatos/<int:contact_id>/gerar-codigo', methods=['POST'])
@login_required
def regenerate_contact_code(contact_id):
    _check_contacts_csrf()
    with contact_write_lock():
        contact = ContactLead.query.get_or_404(contact_id)
        old_code = contact.confirmation_code
        contact.confirmation_code = ''
        get_or_create_contact_code(contact)
        db.session.commit()
    flash(f'Novo código gerado para {contact.name}: {old_code or "-"} → {contact.confirmation_code}.', 'success')
    return redirect(url_for('admin.contacts'))


@admin_bp.route('/contatos/<int:contact_id>/excluir', methods=['POST'])
@login_required
def delete_contact(contact_id):
    _check_contacts_csrf()
    with contact_write_lock():
        contact = ContactLead.query.get_or_404(contact_id)
        for rsvp in list(contact.rsvps):
            db.session.delete(rsvp)
        for dispatch in list(contact.dispatches):
            db.session.delete(dispatch)
        db.session.delete(contact)
        db.session.commit()
    flash('Contato excluído com sucesso.', 'success')
    return redirect(url_for('admin.contacts'))




@admin_bp.route('/whatsapp/conexao', methods=['GET'])
@login_required
def whatsapp_connection():
    settings = SiteSettings.query.first()
    status_data = None
    instance_data = None
    qr_code_image = ''
    error_message = ''
    try:
        status_data = get_instance_status()
        instance_data = get_instance_data()
        if not status_data.get('connected'):
            qr_code_image = get_qrcode_image_base64()
    except Exception as exc:
        error_message = str(exc)

    recent_logs = WhatsAppWebhookLog.query.filter(
        WhatsAppWebhookLog.event_type.in_(['connected', 'disconnected'])
    ).order_by(WhatsAppWebhookLog.created_at.desc()).limit(20).all()

    return render_template(
        'admin/whatsapp_connection.html',
        settings=settings,
        status_data=status_data or {},
        instance_data=instance_data or {},
        qr_code_image=qr_code_image,
        error_message=error_message,
        recent_logs=recent_logs,
    )


@admin_bp.route('/whatsapp/conexao/atualizar-webhooks', methods=['POST'])
@login_required
def whatsapp_connection_update_webhooks():
    try:
        result = configure_instance_webhooks(request.url_root.rstrip('/'))
        flash('O Baileys funciona localmente e não precisa de webhooks externos.', 'success')
    except Exception as exc:
        flash(f'Falha ao consultar o motor do WhatsApp: {exc}', 'danger')
    return redirect(url_for('admin.whatsapp_connection'))


@admin_bp.route('/whatsapp/conexao/reiniciar', methods=['POST'])
@login_required
def whatsapp_connection_restart():
    try:
        restart_instance()
        flash('Comando de reinício enviado para a instância.', 'success')
    except Exception as exc:
        flash(f'Falha ao reiniciar a instância: {exc}', 'danger')
    return redirect(url_for('admin.whatsapp_connection'))


@admin_bp.route('/whatsapp/conexao/desconectar', methods=['POST'])
@login_required
def whatsapp_connection_disconnect():
    try:
        disconnect_instance()
        flash('Instância desconectada. Agora o QR Code deve aparecer para reconectar.', 'warning')
    except Exception as exc:
        flash(f'Falha ao desconectar a instância: {exc}', 'danger')
    return redirect(url_for('admin.whatsapp_connection'))


@admin_bp.route('/campanhas', methods=['GET', 'POST'])
@login_required
def campaigns():
    if request.method == 'POST':
        image_upload = request.files.get('image')
        image_path = save_upload(image_upload) if image_upload and image_upload.filename else ''
        campaign = WhatsAppCampaign(
            title=request.form.get('title', '').strip(),
            message=request.form.get('message', '').strip(),
            active=True,
            target_tag=request.form.get('target_tag', 'todos').strip() or 'todos',
            image_path=image_path,
        )
        db.session.add(campaign)
        db.session.commit()
        flash('Campanha criada. Ela não dispara sozinha: use o botão de envio quando quiser.', 'success')
        return redirect(url_for('admin.campaigns'))

    campaigns = WhatsAppCampaign.query.order_by(WhatsAppCampaign.created_at.desc()).all()
    contacts = ContactLead.query.order_by(ContactLead.created_at.desc()).all()
    dispatches = WhatsAppDispatch.query.order_by(WhatsAppDispatch.created_at.desc()).limit(80).all()
    webhook_logs = WhatsAppWebhookLog.query.order_by(WhatsAppWebhookLog.created_at.desc()).limit(20).all()
    tags = _tag_options()
    settings = SiteSettings.query.first()

    dispatch_summary = {
        'delivered': len([d for d in dispatches if d.status in {'sent', 'delivered', 'delivery', 'received', 'read'}]),
        'queued': len([d for d in dispatches if d.status == 'queued']),
        'error': len([d for d in dispatches if d.status == 'error']),
    }

    campaign_metrics = {}
    for item in campaigns:
        eligible_contacts = [c for c in contacts if item.target_tag == 'todos' or (c.tag or '').strip().lower() == item.target_tag.strip().lower()]
        eligible_ids = {c.id for c in eligible_contacts}
        relevant_dispatches = [d for d in item.dispatches if d.contact_id in eligible_ids]
        delivered_count = len([d for d in relevant_dispatches if d.status in {'sent', 'delivered', 'delivery', 'received', 'read'}])
        queued_count = len([d for d in relevant_dispatches if d.status == 'queued'])
        error_count = len([d for d in relevant_dispatches if d.status == 'error'])
        processed_ids = {d.contact_id for d in relevant_dispatches}
        pending_count = max(0, len(eligible_ids - processed_ids))
        campaign_metrics[item.id] = {
            'eligible': len(eligible_contacts),
            'sent': delivered_count,
            'queued': queued_count,
            'errors': error_count,
            'pending': pending_count,
        }

    whatsapp_status = {}
    whatsapp_error = ''
    try:
        whatsapp_status = get_instance_status()
    except Exception as exc:
        whatsapp_error = str(exc)

    return render_template(
        'admin/campaigns.html',
        campaigns=campaigns,
        contacts=contacts,
        dispatches=dispatches,
        tags=tags,
        settings=settings,
        webhook_logs=webhook_logs,
        campaign_metrics=campaign_metrics,
        dispatch_summary=dispatch_summary,
        whatsapp_status=whatsapp_status,
        whatsapp_error=whatsapp_error,
    )


@admin_bp.route('/campanhas/<int:campaign_id>/disparar', methods=['POST'])
@login_required
def trigger_campaign(campaign_id):
    campaign = WhatsAppCampaign.query.get_or_404(campaign_id)
    contacts = ContactLead.query.order_by(ContactLead.created_at.asc()).all()
    send_scope = (request.form.get('send_scope', 'unsent') or 'unsent').strip()
    site_url = request.url_root.rstrip('/')
    settings = SiteSettings.query.first()

    try:
        batch_size = int(request.form.get('batch_size', 20) or 20)
    except (TypeError, ValueError):
        batch_size = 20
    batch_size = max(1, min(batch_size, 50))

    try:
        results = send_campaign_messages(
            campaign,
            contacts,
            tag_filter=campaign.target_tag,
            send_scope=send_scope,
            settings=settings,
            site_url=site_url,
            batch_size=batch_size,
        )
        sent = len([r for r in results if r['status'] == 'sent'])
        skipped = len([r for r in results if r['status'] == 'skipped'])
        errors = len([r for r in results if r['status'] == 'error'])
        scope_label = {
            'unsent': 'pendentes',
            'errors': 'com erro',
            'all': 'selecionados',
        }.get(send_scope, 'selecionados')
        flash(f'Lote processado para contatos {scope_label}. Limite do lote: {batch_size} | Enviados: {sent} | Ignorados: {skipped} | Erros: {errors}.', 'success' if errors == 0 else 'warning')
    except WhatsAppConfigError as exc:
        flash(str(exc), 'danger')
    except Exception as exc:
        current_app.logger.exception('Falha ao disparar campanha %s', campaign_id)
        db.session.rollback()
        flash(f'Erro interno ao processar o lote da campanha: {exc}', 'danger')
    return redirect(url_for('admin.campaigns'))


@admin_bp.route('/campanhas/<int:campaign_id>/excluir', methods=['POST'])
@login_required
def delete_campaign(campaign_id):
    campaign = WhatsAppCampaign.query.get_or_404(campaign_id)
    for dispatch in campaign.dispatches:
        db.session.delete(dispatch)
    db.session.delete(campaign)
    db.session.commit()
    flash('Campanha excluída.', 'success')
    return redirect(url_for('admin.campaigns'))
