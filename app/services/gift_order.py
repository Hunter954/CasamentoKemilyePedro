"""Gift positions are independent of price, availability and purchase history."""
import threading
from random import shuffle
from contextlib import contextmanager
from sqlalchemy import text
from app import db
from app.models import GiftItem

_order_lock = threading.RLock()


def admin_gifts_query():
    return GiftItem.query.order_by(GiftItem.display_order.asc().nullslast(),
                                  GiftItem.created_at.desc(), GiftItem.id.desc())


def ordered_public_gifts():
    gifts = admin_gifts_query().filter_by(active=True).all()
    positioned = [gift for gift in gifts if gift.display_order is not None]
    automatic = [gift for gift in gifts if gift.display_order is None]
    shuffle(automatic)
    return positioned + automatic


@contextmanager
def gift_order_lock():
    with _order_lock:
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text('SELECT pg_advisory_xact_lock(74201953)'))
            yield
        except Exception:
            db.session.rollback()
            raise


def move_gift(gift_id, position):
    with gift_order_lock():
        gifts = admin_gifts_query().populate_existing().with_for_update().all()
        target = next((gift for gift in gifts if gift.id == gift_id), None)
        if target is None:
            raise LookupError('Este presente não foi encontrado. Atualize a página.')
        if not 1 <= position <= len(gifts):
            raise ValueError(f'Informe uma posição entre 1 e {len(gifts)}.')
        gifts.remove(target)
        gifts.insert(position - 1, target)
        for index, gift in enumerate(gifts, 1):
            gift.display_order = index
        db.session.commit()
        return {str(gift.id): gift.display_order for gift in gifts}
