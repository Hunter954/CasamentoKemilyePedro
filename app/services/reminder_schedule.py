from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.models import WhatsAppCampaign, WhatsAppDispatch
from app.services.campaign_audience import audience_contacts

LOCAL_ZONE = ZoneInfo('America/Sao_Paulo')
DEFAULT_DEADLINE = '2026-11-05'
DEFAULT_WAIT_HOURS = 24
SENT_STATUSES = ('sent', 'delivered', 'delivery', 'received', 'read')


def local_send_time(value, pattern='%d/%m/%Y às %H:%M'):
    return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_ZONE).strftime(pattern)


def invite_campaigns(reminder):
    return (WhatsAppCampaign.query.join(WhatsAppDispatch)
            .filter(WhatsAppCampaign.id != reminder.id, WhatsAppCampaign.scheduled_reminder.is_(False),
                    WhatsAppDispatch.status.in_(SENT_STATUSES), WhatsAppDispatch.sent_at.is_not(None))
            .order_by(WhatsAppCampaign.created_at.desc(), WhatsAppCampaign.id.desc()).all())


def reminder_plan(campaign, source_ids, wait_hours, deadline, now=None):
    now = now or datetime.utcnow()
    if wait_hours is None or not 1 <= wait_hours <= 720:
        raise ValueError('Informe uma espera entre 1 e 720 horas após o primeiro convite.')
    try:
        day_after = date.fromisoformat(deadline) + timedelta(days=1)
        expires_at = datetime.combine(day_after, time.min, LOCAL_ZONE).astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise ValueError('Informe uma data limite válida.') from None
    if not source_ids or not set(source_ids).issubset({source.id for source in invite_campaigns(campaign)}):
        raise ValueError('Selecione as campanhas que enviaram os convites originais.')

    first_invites = dict(WhatsAppDispatch.query.with_entities(WhatsAppDispatch.contact_id, func.min(WhatsAppDispatch.sent_at))
                         .filter(WhatsAppDispatch.campaign_id.in_(source_ids), WhatsAppDispatch.status.in_(SENT_STATUSES),
                                 WhatsAppDispatch.sent_at <= now)
                         .group_by(WhatsAppDispatch.contact_id).all())
    processed = {dispatch.contact_id for dispatch in campaign.dispatches}
    rows = []
    for contact in audience_contacts(campaign):
        if contact.id in processed:
            continue
        first = first_invites.get(contact.id)
        release = first + timedelta(hours=wait_hours) if first else None
        if release is None:
            state = 'missing'
        elif max(release, now) >= expires_at:
            state = 'expired'
        else:
            state = 'ready' if release <= now else 'scheduled'
        rows.append({'contact': contact, 'first': first, 'release': release, 'state': state})
    rows.sort(key=lambda row: (row['release'] is None, row['release'], row['contact'].name.casefold(), row['contact'].id))
    return rows, expires_at
