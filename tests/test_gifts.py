import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)

from app import create_app, db
from app.models import GiftItem, GiftPurchase, GiftCatalogRelease
from app.gift_catalog import seed_gift_catalog, INITIAL_GIFTS, ADDITIONAL_GIFTS, RELEASE_KEY


class GiftStorefrontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def test_empty_database_receives_18_gifts_and_local_photos(self):
        self.assertEqual(seed_gift_catalog(), 18)
        self.assertEqual(GiftItem.query.count(), 18)
        for gift in GiftItem.query.all():
            self.assertTrue((Path(self.app.static_folder) / gift.image_url.removeprefix('/static/')).exists())

    def test_existing_gifts_and_purchases_are_preserved(self):
        gift = GiftItem(title='Presente personalizado', price=731.25, active=False, image_url='/media/foto.jpg', allow_multiple_purchases=False)
        db.session.add(gift)
        db.session.flush()
        purchase = GiftPurchase(gift_id=gift.id, buyer_name='Teste', buyer_email='teste@example.com', buyer_phone='11999999999', amount=731.25, status='approved')
        db.session.add(purchase)
        db.session.commit()
        self.assertEqual(seed_gift_catalog(), 12)
        self.assertEqual((gift.price, gift.active, gift.image_url, gift.is_sold_out), (731.25, False, '/media/foto.jpg', True))
        self.assertEqual(GiftPurchase.query.count(), 1)
        self.assertEqual(GiftItem.query.count(), 13)

    def test_restarts_do_not_restore_deleted_or_disabled_gifts(self):
        seed_gift_catalog()
        removed = GiftItem.query.first()
        db.session.delete(removed)
        disabled = GiftItem.query.filter(GiftItem.id != removed.id).first()
        disabled.active = False
        db.session.commit()
        self.assertEqual(seed_gift_catalog(), 0)
        self.assertEqual(GiftItem.query.count(), 17)
        self.assertFalse(disabled.active)

    def test_matching_existing_title_is_not_overwritten(self):
        gift = GiftItem(title=ADDITIONAL_GIFTS[0]['title'], price=42, active=False)
        db.session.add(gift)
        db.session.commit()
        self.assertEqual(seed_gift_catalog(), 11)
        self.assertEqual((gift.price, gift.active), (42, False))

    def test_failed_release_rolls_back_marker_and_gifts(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                seed_gift_catalog()
        db.session.rollback()
        self.assertIsNone(db.session.get(GiftCatalogRelease, RELEASE_KEY))
        self.assertEqual(GiftItem.query.count(), 0)
        self.assertEqual(seed_gift_catalog(), 18)

    def test_listing_and_checkout_respect_availability(self):
        seed_gift_catalog()
        gift = GiftItem.query.order_by(GiftItem.price.asc()).first()
        response = self.client.get('/presentes')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertEqual(text.count('<article class="kp-gift-card'), 18)
        self.assertIn('R$ 49,90', text)
        self.assertIn('id="kp-gift-search"', text)
        self.assertIn('id="kp-gift-budget"', text)
        self.assertEqual(self.client.get(f'/presentes/{gift.id}/checkout').status_code, 200)
        gift.allow_multiple_purchases = False
        db.session.add(GiftPurchase(gift_id=gift.id, buyer_name='Teste', buyer_email='teste@example.com', buyer_phone='11999999999', amount=gift.price, status='approved'))
        db.session.commit()
        self.assertIn('kp-gift-unavailable', self.client.get('/presentes').get_data(as_text=True))
        self.assertEqual(self.client.get(f'/presentes/{gift.id}/checkout').status_code, 302)


if __name__ == '__main__':
    unittest.main()
