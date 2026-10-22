import os
import unittest
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)

from app import create_app, db
from app.models import AdminUser, ContactLead


class ContactNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='contact-name-test-only')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        admin = AdminUser(name='Teste', email='name@example.test')
        admin.set_password('test-only')
        self.contact = ContactLead(name='Nome antigo', phone='45999991234',
                                   tag='familia', confirmation_code='123456', email='guest@example.test')
        db.session.add_all([admin, self.contact])
        db.session.commit()
        self.url = f'/admin/contatos/{self.contact.id}/nome'
        self.client = self.app.test_client()
        with self.client.session_transaction() as state:
            state['_user_id'] = str(admin.id)
            state['_fresh'] = True
            state['contacts_csrf'] = 'name-test-token'

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def save(self, name, **extra):
        return self.client.post(self.url, data={'csrf_token': 'name-test-token', 'name': name, **extra})

    def test_rename_preserves_other_fields_and_renders_editor(self):
        response = self.save('  João & Maria  ', phone='000', tag='changed', confirmation_code='000000')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'id': self.contact.id, 'name': 'João & Maria', 'people_count': 2})
        db.session.expire_all()
        self.assertEqual((self.contact.name, self.contact.phone, self.contact.tag,
                          self.contact.confirmation_code, self.contact.email),
                         ('João & Maria', '45999991234', 'familia', '123456', 'guest@example.test'))
        html = self.client.get('/admin/contatos').get_data(as_text=True)
        self.assertIn('data-name-editor', html)
        self.assertIn(f'action="{self.url}"', html)
        self.assertIn('João &amp; Maria', html)

    def test_validation_authentication_and_csrf(self):
        for name in ('', '   ', 'x' * 181):
            self.assertEqual(self.save(name).status_code, 422)
        self.assertEqual(self.client.post(self.url, data={'name': 'Changed'}).status_code, 400)
        self.assertEqual(self.client.post('/admin/contatos/999999/nome',
                         data={'csrf_token': 'name-test-token', 'name': 'Changed'}).status_code, 404)
        db.session.expire_all()
        self.assertEqual(self.contact.name, 'Nome antigo')

    def test_requires_login(self):
        self.assertEqual(self.app.test_client().post(self.url, data={'name': 'Changed'}).status_code, 302)

    def test_commit_failure_reports_error_and_preserves_name(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('test failure')):
            self.assertEqual(self.save('Changed').status_code, 503)
        db.session.expire_all()
        self.assertEqual(self.contact.name, 'Nome antigo')
