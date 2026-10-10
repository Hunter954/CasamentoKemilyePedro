"""Durable, globally paced campaign queue. No automatic retry after ambiguous sends."""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from sqlalchemy import text, func
from app import db
from app.models import CampaignDelivery, CampaignJob, WhatsAppCampaign, WhatsAppDispatch, ContactLead, SiteSettings
from app.services.whatsapp import (normalize_whatsapp_phone, render_campaign_message, to_public_media_url,
                                   get_instance_status, _post_send_text, _post_send_image, serialize_payload)

_local_lock = threading.Lock()


class QueueBusy(ValueError):
    pass


@contextmanager
def queue_lock():
    # Session advisory lock survives the commit BEFORE calling WhatsApp, and is
    # released explicitly on the same dedicated connection, including failures.
    connection = None
    acquired = False
    try:
        if db.engine.dialect.name == 'postgresql':
            connection = db.engine.connect()
            acquired = bool(connection.execute(text('SELECT pg_try_advisory_lock(76260115)')).scalar())
        else:
            acquired = _local_lock.acquire(blocking=False)
        if not acquired:
            raise QueueBusy('Um envio está em andamento. Aguarde alguns segundos e tente novamente.')
        yield
    finally:
        if acquired:
            if connection:
                connection.execute(text('SELECT pg_advisory_unlock(76260115)'))
            else:
                _local_lock.release()
        if connection:
            connection.close()


def delivery_settings():
    settings = db.session.get(CampaignDelivery, 1)
    if settings is None:
        settings = CampaignDelivery(id=1, interval_seconds=15)
        db.session.add(settings)
        db.session.flush()
    return settings


def queue_campaign(campaign, site_url, scope='unsent'):
    if scope not in ('unsent', 'errors'):
        raise ValueError('Selecione pendentes ou erros para enviar.')
    with queue_lock():
        if not campaign.active:
            raise ValueError('Esta campanha está desativada.')
        settings = SiteSettings.query.first()
        image = to_public_media_url(campaign.image_path or '', site_url=site_url)
        count = 0
        existing_dispatches = {dispatch.contact_id: dispatch for dispatch in WhatsAppDispatch.query.filter_by(campaign_id=campaign.id).all()}
        for contact in ContactLead.query.order_by(ContactLead.id).all():
            if scope == 'unsent' and campaign.target_tag != 'todos' and (contact.tag or '').strip().lower() != campaign.target_tag.strip().lower():
                continue
            dispatch = existing_dispatches.get(contact.id)
            if scope == 'errors':
                if not dispatch or dispatch.status not in ('error', 'uncertain'):
                    continue
                # Retry only failed parts: do not resend an already delivered image.
                failed = [job for job in dispatch.jobs if job.status in ('error', 'uncertain')]
                if failed:
                    for job in failed:
                        job.status, job.error, job.started_at = 'queued', '', None
                    dispatch.status, dispatch.error_message = 'queued', ''
                    count += 1
                    continue
            elif dispatch:
                continue
            phone = normalize_whatsapp_phone(contact.phone)
            if not phone:
                continue
            if dispatch is None:
                dispatch = WhatsAppDispatch(campaign_id=campaign.id, contact_id=contact.id)
                db.session.add(dispatch)
            dispatch.status, dispatch.phone_sent, dispatch.error_message = 'queued', phone, ''
            message = render_campaign_message(campaign.message, contact, settings, site_url)
            if image:
                db.session.add(CampaignJob(dispatch=dispatch, kind='image', phone=phone, image_url=image,
                                           message=message if len(message) <= 1024 else ''))
            if not image or len(message) > 1024:
                db.session.add(CampaignJob(dispatch=dispatch, kind='text', phone=phone, message=message))
            count += 1
        if count and scope == 'errors':
            campaign.queue_paused = False
        db.session.commit()
        return count


def queue_overview():
    groups = (db.session.query(WhatsAppDispatch.campaign_id, CampaignJob.status, func.count(CampaignJob.id))
              .join(CampaignJob, CampaignJob.dispatch_id == WhatsAppDispatch.id)
              .group_by(WhatsAppDispatch.campaign_id, CampaignJob.status).all())
    paused = dict(db.session.query(WhatsAppCampaign.id, WhatsAppCampaign.queue_paused).all())
    interval = delivery_settings().interval_seconds
    overview = {}
    for cid, status, count in groups:
        data = overview.setdefault(cid, {'total': 0, 'sent': 0, 'queued': 0, 'sending': 0, 'error': 0, 'uncertain': 0})
        data['total'] += count
        if status in data:
            data[status] += count
    for cid, data in overview.items():
        data['remaining'] = data['queued'] + data['sending']
        data['minutes'] = (data['remaining'] * interval + 59) // 60
        data['percent'] = round(100 * data['sent'] / data['total']) if data['total'] else 0
        data['paused'] = paused.get(cid, True)
    return overview


def process_next(now=None):
    now = now or datetime.utcnow()
    try:
        with queue_lock():
            pacing = delivery_settings()
            # A process may have died after sending but before recording success.
            # Stop and require review; retrying automatically could duplicate it.
            for stale in CampaignJob.query.filter(CampaignJob.status == 'sending', CampaignJob.started_at < now - timedelta(seconds=120)).all():
                stale.status = 'uncertain'
                stale.error = 'Envio interrompido. Confira a conversa antes de reenviar: a mensagem pode ter sido entregue.'
                stale.dispatch.status = 'uncertain'
                stale.dispatch.error_message = stale.error
                stale.dispatch.campaign.queue_paused = True
            db.session.commit()
            if CampaignJob.query.filter_by(status='sending').first():
                return {'state': 'busy'}
            if pacing.next_send_at and pacing.next_send_at > now:
                return {'state': 'waiting'}
            job = (CampaignJob.query.join(WhatsAppDispatch).join(WhatsAppCampaign)
                   .filter(CampaignJob.status == 'queued', WhatsAppCampaign.queue_paused.is_(False), WhatsAppCampaign.active.is_(True))
                   .order_by(CampaignJob.id).first())
            if job is None:
                return {'state': 'idle'}
            if not get_instance_status().get('connected'):
                return {'state': 'disconnected'}
            job.status, job.started_at = 'sending', now
            pacing.next_send_at = now + timedelta(seconds=max(15, pacing.interval_seconds))
            db.session.commit()
            try:
                response = (_post_send_image(job.phone, job.image_url, job.message) if job.kind == 'image'
                            else _post_send_text(job.phone, job.message))
                if not response.get('message_id'):
                    raise ValueError('Provedor não confirmou o identificador da mensagem. Confira a conversa antes de reenviar.')
                job.status, job.provider_message_id, job.error = 'sent', response['message_id'], ''
                job.dispatch.response_body = serialize_payload(response)
                db.session.flush()
                if not any(part.status != 'sent' for part in job.dispatch.jobs):
                    job.dispatch.provider_message_id = job.provider_message_id
                    if job.dispatch.status not in ('delivered', 'read'):
                        job.dispatch.status = 'sent'
                    job.dispatch.sent_at = datetime.utcnow()
                    job.dispatch.error_message = ''
                state = 'sent'
            except Exception as exc:
                job.status = 'error'
                job.error = str(exc)[:2000]
                job.dispatch.status, job.dispatch.error_message = 'error', job.error
                job.dispatch.campaign.queue_paused = True
                state = 'error'
            # The interval applies to every physical message, even after errors.
            pacing.next_send_at = max(now, datetime.utcnow()) + timedelta(seconds=max(15, pacing.interval_seconds))
            db.session.commit()
            return {'state': state}
    except QueueBusy:
        return {'state': 'busy'}
