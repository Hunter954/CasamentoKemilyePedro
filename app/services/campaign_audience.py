"""One audience rule shared by previews, queue creation and delivery."""
from sqlalchemy.orm import selectinload
from app.models import ContactLead
from app.services.whatsapp import normalize_whatsapp_phone

AUDIENCES = {'all': 'Todas as respostas', 'pending': 'Ainda não responderam',
             'yes': 'Presença confirmada', 'no': 'Não comparecerão',
             'partial': 'Presença parcial'}


def matches_audience(campaign, contact, include_tag=True):
    if include_tag and campaign.target_tag != 'todos' and (contact.tag or '').strip().casefold() != campaign.target_tag.strip().casefold():
        return False
    status = campaign.target_rsvp or 'all'
    if status == 'partial':
        return contact.rsvp_status == 'yes' and contact.accepted_people < contact.people_count
    return status == 'all' or status == contact.rsvp_status


def audience_contacts(campaign, retry=False):
    return [contact for contact in ContactLead.query.options(selectinload(ContactLead.rsvps)).order_by(ContactLead.name, ContactLead.id).all()
            if matches_audience(campaign, contact, include_tag=not retry) and normalize_whatsapp_phone(contact.phone)]
