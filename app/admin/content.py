import re
from datetime import datetime
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import Ceremony, FAQ, SiteSettings
from app.utils import save_upload
from app.admin.security import check_panel_csrf

content_bp = Blueprint('admin_content', __name__)


@content_bp.route('/cerimonias', methods=['GET', 'POST'])
@login_required
def ceremonies():
    if request.method == 'POST':
        check_panel_csrf()
        item = db.get_or_404(Ceremony, request.form.get('ceremony_id', type=int))
        title, venue = request.form.get('title', '').strip(), request.form.get('venue', '').strip()
        clock, raw_date = request.form.get('event_time', ''), request.form.get('event_date', '')
        route = request.form.get('route_url', '').strip()
        try:
            if not title or not venue or len(title) > 120 or len(venue) > 180:
                raise ValueError('Informe o título e o local da cerimônia.')
            if clock and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
                raise ValueError('Informe um horário válido.')
            event_date = datetime.strptime(raw_date, '%Y-%m-%d').date() if raw_date else None
            if route and (urlparse(route).scheme not in ('https', 'http') or not urlparse(route).netloc or len(route) > 1000):
                raise ValueError('Use um link de rota http ou https válido.')
        except ValueError as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('admin_content.ceremonies'))
        item.title, item.venue, item.event_time, item.event_date, item.route_url = title, venue, clock, event_date, route
        item.address = request.form.get('address', '').strip()[:255]
        item.city = request.form.get('city', '').strip()[:120]
        upload = request.files.get('image')
        if upload and upload.filename:
            item.image_path = save_upload(upload)
        if item.kind == 'church':
            settings = SiteSettings.query.first()
            if settings:
                settings.wedding_location_name, settings.wedding_address, settings.wedding_city = item.venue, item.address, item.city
                settings.wedding_time, settings.route_url = item.event_time, item.maps_url
                if item.event_date:
                    settings.wedding_date = datetime.combine(item.event_date, datetime.strptime(clock or '00:00', '%H:%M').time())
        db.session.commit()
        flash('Cerimônia atualizada. Local e horário já aparecem no site.', 'success')
        return redirect(url_for('admin_content.ceremonies'))
    return render_template('admin/ceremonies.html', ceremonies=Ceremony.query.order_by(Ceremony.id).all())


@content_bp.route('/perguntas-frequentes', methods=['GET', 'POST'])
@login_required
def faqs():
    if request.method == 'POST':
        check_panel_csrf()
        item_id = request.form.get('faq_id', type=int)
        item = db.get_or_404(FAQ, item_id) if item_id else FAQ()
        question, answer = request.form.get('question', '').strip(), request.form.get('answer', '').strip()
        if not question or len(question) > 255 or not answer or len(answer) > 5000:
            flash('Informe uma pergunta (até 255 caracteres) e uma resposta (até 5.000 caracteres).', 'danger')
        else:
            item.question, item.answer = question, answer
            item.position = max(0, min(request.form.get('position', 0, type=int) or 0, 999))
            item.active = request.form.get('active') == 'on'
            db.session.add(item)
            db.session.commit()
            flash('Pergunta salva com sucesso.', 'success')
        return redirect(url_for('admin_content.faqs'))
    edit_id = request.args.get('edit', type=int)
    return render_template('admin/faqs.html', faqs=FAQ.query.order_by(FAQ.position, FAQ.id).all(),
                           editing=db.get_or_404(FAQ, edit_id) if edit_id else None)


@content_bp.route('/perguntas-frequentes/<int:faq_id>/excluir', methods=['POST'])
@login_required
def delete_faq(faq_id):
    check_panel_csrf()
    db.session.delete(db.get_or_404(FAQ, faq_id))
    db.session.commit()
    flash('Pergunta excluída.', 'success')
    return redirect(url_for('admin_content.faqs'))
