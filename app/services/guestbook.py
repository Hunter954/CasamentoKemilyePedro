"""Only validated RSVP replies and approved gifts can create new wall messages."""
from app import db
from app.models import GuestbookMessage, SiteSettings, RSVP, GiftPurchase, ContentRelease


def attach_message(source, source_type):
    settings = SiteSettings.query.first()
    content = (source.message or '').strip()
    if not content or (settings and not settings.allow_guestbook):
        return None
    if source_type == 'purchase' and (source.status != 'approved' or not source.payment_verified):
        return None
    if source_type == 'rsvp' and not source.confirmed_at:
        return None
    key = f'{source_type}:{source.id}'
    existing = GuestbookMessage.query.filter_by(source_key=key).first()
    if source.guestbook_synced:
        return existing
    if existing:
        source.guestbook_synced = True
        return existing
    name = source.buyer_name if source_type == 'purchase' else source.guest_name
    # Reuse an identical legacy message instead of showing the same words twice.
    legacy = GuestbookMessage.query.filter_by(source_key=None, author_name=name[:120], message=content[:3000]).first()
    if legacy:
        legacy.source_key = key
        source.guestbook_synced = True
        return legacy
    item = GuestbookMessage(author_name=name[:120], message=content[:3000], source_key=key,
                            approved=not (settings.require_guestbook_approval if settings else True))
    db.session.add(item)
    source.guestbook_synced = True
    return item


def import_existing_messages():
    if db.session.get(ContentRelease, 'verified-guestbook-v1'):
        return
    for item in RSVP.query.filter(RSVP.confirmed_at.isnot(None)).all():
        attach_message(item, 'rsvp')
    for item in GiftPurchase.query.filter_by(status='approved', payment_verified=True).all():
        attach_message(item, 'purchase')
    db.session.add(ContentRelease(key='verified-guestbook-v1'))
    db.session.commit()
