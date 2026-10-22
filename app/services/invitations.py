"""Shared, read-only invitation reporting. Historical RSVP snapshots stay intact."""
from sqlalchemy.orm import selectinload
from datetime import datetime
from app import db
from app.models import ContactLead, RSVP
from app.guest_counts import invitation_names
from app.utils import format_phone
from app.services.guestbook import attach_message


def record_invitation_response(contact, attendance, message='', allow_change=False):
    """Caller holds contact_write_lock and commits. Public replies are idempotent."""
    existing = contact.latest_rsvp
    if existing and existing.confirmed_at and not allow_change:
        return existing
    existing = existing or RSVP(contact_id=contact.id)
    existing.guest_name = contact.name
    existing.phone = format_phone(contact.phone)
    existing.email = existing.email or (contact.email or '').strip()
    existing.guests_count = contact.people_count if attendance == 'yes' else 0
    existing.attendance = attendance
    existing.message = message
    existing.confirmation_code = contact.confirmation_code
    existing.confirmed_at = datetime.utcnow()
    db.session.add(existing)
    db.session.flush()
    attach_message(existing, 'rsvp')
    return existing


def invitation_report():
    contacts = ContactLead.query.options(selectinload(ContactLead.rsvps)).order_by(ContactLead.created_at.desc(), ContactLead.id.desc()).all()
    rows = [{'contact': contact, 'rsvp': contact.latest_rsvp, 'status': contact.rsvp_status,
             'people': contact.people_count} for contact in contacts]
    legacy = RSVP.query.filter(RSVP.contact_id.is_(None)).order_by(RSVP.created_at.desc(), RSVP.id.desc()).all()
    totals = {'invites': len(rows), 'people': sum(row['people'] for row in rows),
              'yes': 0, 'no': 0, 'pending': 0, 'responded_invites': 0}
    for row in rows:
        totals[row['status']] += row['people']
        totals['responded_invites'] += int(row['status'] != 'pending')
    # Unlinked manual records retain the originally recorded accepted quantity.
    for item in legacy:
        if item.attendance not in ('yes', 'no'):
            continue
        people = max(0, item.guests_count or 0) if item.attendance == 'yes' else len(invitation_names(item.guest_name))
        totals[item.attendance] += people
        totals['people'] += people
    return rows, legacy, totals
