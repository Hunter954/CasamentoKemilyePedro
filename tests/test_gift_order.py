import os
import unittest
from unittest.mock import patch
from sqlalchemy import text, inspect

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)

from app import create_app, db, _sync_schema
from app.models import AdminUser, GiftItem, GiftPurchase
from app.services.gift_order import admin_gifts_query, ordered_public_gifts


class GiftOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='gift-order-tests-only')

    def setUp(self):
        self.context = self.app.app_context(); self.context.push()
        db.drop_all(); db.create_all()
        admin = AdminUser(name='Teste', email='order@example.test'); admin.set_password('test-only')
        db.session.add(admin)
        self.gifts = [GiftItem(title=f'Presente {index}', price=price, image_url=f'/media/{index}.jpg',
                              description=f'Descrição {index}') for index, price in enumerate([500, 100, 300], 1)]
        db.session.add_all(self.gifts); db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_user_id'] = admin.get_id(); state['_fresh'] = True; state['panel_csrf'] = 'order-token'

    def tearDown(self):
        db.session.remove(); self.context.pop()

    def move(self, gift, position):
        return self.client.post(f'/admin/presentes/{gift.id}/ordem',
                                data={'csrf_token': 'order-token', 'position': position})

    def test_move_updates_exact_positions_and_public_order(self):
        target = self.gifts[0]
        response = self.move(target, '1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['position'], 1)
        self.assertEqual([g.id for g in ordered_public_gifts()], [target.id, self.gifts[2].id, self.gifts[1].id])
        self.move(self.gifts[2], '3')
        self.assertEqual([g.id for g in admin_gifts_query().all()], [g.id for g in self.gifts])
        self.assertEqual(sorted(response.json['positions'].values()), [1, 2, 3])
        html = self.client.get('/presentes').get_data(as_text=True)
        self.assertLess(html.index('Ver presente: Presente 1'), html.index('Ver presente: Presente 2'))
        self.assertLess(html.index('Ver presente: Presente 2'), html.index('Ver presente: Presente 3'))

    def test_prices_images_and_purchases_are_preserved(self):
        gift = self.gifts[0]
        purchase = GiftPurchase(gift_id=gift.id, buyer_name='Teste', buyer_email='test@example.test',
                                buyer_phone='45999991234', amount=500, status='approved')
        db.session.add(purchase); db.session.commit()
        self.move(gift, '2')
        db.session.expire_all()
        self.assertEqual((gift.title, gift.description, gift.price, gift.image_url, gift.active),
                         ('Presente 1', 'Descrição 1', 500, '/media/1.jpg', True))
        self.assertEqual((purchase.amount, purchase.status, purchase.gift_id), (500, 'approved', gift.id))

    def test_invalid_positions_missing_gift_and_csrf_do_not_change_order(self):
        for value in ('', '0', '-1', '4', '1.5', 'text', '9' * 100):
            self.assertEqual(self.move(self.gifts[0], value).status_code, 422)
        self.assertEqual(self.client.post('/admin/presentes/99999/ordem',
            data={'csrf_token': 'order-token', 'position': '1'}).status_code, 404)
        self.assertEqual(self.client.post(f'/admin/presentes/{self.gifts[0].id}/ordem',
            data={'position': '1'}).status_code, 400)
        self.assertTrue(all(g.display_order is None for g in self.gifts))

    def test_requires_login(self):
        self.assertEqual(self.app.test_client().post(f'/admin/presentes/{self.gifts[0].id}/ordem',
                                                   data={'position': '1'}).status_code, 302)

    def test_random_default_and_unavailable_gifts_keep_existing_behavior(self):
        with patch('app.services.gift_order.shuffle') as shuffle:
            self.assertEqual(len(ordered_public_gifts()), 3)
            shuffle.assert_called_once()
        self.move(self.gifts[0], '1')
        self.gifts[0].active = False; db.session.commit()
        self.assertNotIn(self.gifts[0], ordered_public_gifts())
        html = self.client.get('/admin/presentes').get_data(as_text=True)
        self.assertEqual(html.count('data-order-form hidden'), 3)
        self.assertIn('Editar ordem', html)

    def test_commit_error_rolls_back_and_additive_migration_preserves_gifts(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('test failure')):
            self.assertEqual(self.move(self.gifts[0], '1').status_code, 503)
        db.session.expire_all()
        self.assertTrue(all(g.display_order is None for g in self.gifts))
        db.session.execute(text('ALTER TABLE gift_item DROP COLUMN display_order')); db.session.commit()
        _sync_schema(self.app)
        self.assertIn('display_order', {col['name'] for col in inspect(db.engine).get_columns('gift_item')})
        self.assertEqual(GiftItem.query.count(), 3)
