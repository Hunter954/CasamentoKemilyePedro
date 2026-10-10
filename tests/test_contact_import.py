import os
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)
from app import create_app, db
from app.models import AdminUser, ContactLead, ContactImportEvent, ContactImportSettings, RSVP
from app.services.contact_import import clean_phone, phone_key, import_contacts
from app.services.whatsapp import normalize_whatsapp_phone, _post_send_text
from app.utils import format_phone


class ContactImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='test-only', WA_INTERNAL_TOKEN='internal-test-only')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        admin = AdminUser(name='Noivos', email='test@example.test')
        admin.set_password('test-only')
        db.session.add_all([admin, ContactImportSettings(id=1, enabled=True, group_jid='123@g.us',
                            group_name='Convidados', activated_at=datetime.utcnow() - timedelta(seconds=60))])
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(admin.id)
            session['_fresh'] = True
            session['contacts_csrf'] = 'csrf-test'

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def payload(self, **overrides):
        payload = {'groupJid': '123@g.us', 'messageId': 'first:0', 'timestamp': time.time(),
                   'senderName': 'Kemily', 'contacts': [{'name': 'Ana', 'phone': '+55 (45) 99999-1234'}]}
        payload.update(overrides)
        return payload

    def post(self, payload, token='internal-test-only'):
        return self.client.post('/api/whatsapp/contacts/import', json=payload,
                                headers={'X-WA-Internal-Token': token})

    def test_import_generates_unique_codes_and_replay_does_not_duplicate(self):
        payload = self.payload(contacts=[{'name': 'Ana', 'phone': '45999991234'}, {'name': 'Pedro', 'phone': '+5545999984321'}])
        self.assertEqual(self.post(payload).json['created'], 2)
        codes = [item.confirmation_code for item in ContactLead.query.all()]
        self.assertEqual(len(set(codes)), 2)
        self.assertTrue(all(len(code) == 6 and code.isdigit() for code in codes))
        self.assertTrue(self.post(payload).json['replayed'])
        self.assertEqual(ContactLead.query.count(), 2)
        self.assertEqual(ContactImportEvent.query.count(), 1)

    def test_existing_contact_rsvp_name_tag_and_code_are_preserved(self):
        contact = ContactLead(name='Ana & João', phone='(45) 99999-1234', tag='padrinhos', confirmation_code='112233')
        db.session.add(contact)
        db.session.flush()
        db.session.add(RSVP(contact_id=contact.id, guest_name=contact.name, phone=contact.phone, attendance='yes'))
        db.session.commit()
        result = self.post(self.payload()).json
        self.assertEqual((result['created'], result['duplicates']), (0, 1))
        self.assertEqual((contact.name, contact.tag, contact.confirmation_code), ('Ana & João', 'padrinhos', '112233'))
        self.assertEqual(RSVP.query.count(), 1)

    def test_brazil_mobile_aliases_repeat_within_batch_and_landline(self):
        self.assertEqual(phone_key('4599991234'), phone_key('45999991234'))
        self.assertNotEqual(phone_key('4533331234'), phone_key('45933331234'))
        result = import_contacts(self.payload(contacts=[{'name': 'Ana', 'phone': '+554599991234'},
            {'name': 'Outra Ana', 'phone': '45999991234'}, {'name': 'Casa', 'phone': '4533331234'}]))
        self.assertEqual((result['created'], result['duplicates']), (2, 1))

    def test_invalid_cards_logged_and_valid_cards_still_imported(self):
        self.assertEqual(clean_phone('99991234'), '')
        result = import_contacts(self.payload(contacts=[{'name': 'Sem telefone'}, {'name': '', 'phone': '45999991234'},
            {'name': 'Curto', 'phone': '123'}, {'name': 'Ana', 'phone': '45999991234'}]))
        self.assertEqual((result['created'], result['invalid']), (1, 3))
        self.assertEqual(ContactImportEvent.query.first().invalid_count, 3)

    def test_wrong_group_old_cards_and_paused_imports_ignored(self):
        self.assertTrue(self.post(self.payload(groupJid='other@g.us')).json['ignored'])
        self.assertTrue(self.post(self.payload(timestamp=time.time() - 120)).json['ignored'])
        db.session.get(ContactImportSettings, 1).enabled = False
        db.session.commit()
        self.assertTrue(self.post(self.payload()).json['ignored'])
        self.assertEqual(ContactLead.query.count(), 0)
        self.assertEqual(ContactImportEvent.query.count(), 0)

    def test_endpoint_rejects_missing_or_wrong_secret_and_bad_payloads(self):
        self.assertEqual(self.post(self.payload(), token='').status_code, 403)
        self.assertEqual(self.post(self.payload(), token='bad').status_code, 403)
        for payload in (None, [], self.payload(timestamp='oops'), self.payload(contacts=[]), self.payload(contacts=[{}] * 101)):
            self.assertEqual(self.post(payload).status_code, 400)
        self.assertEqual(self.post(self.payload(contacts=[{'name': 'x' * 270000}])).status_code, 413)

    def test_failed_commit_rolls_back_contacts_and_idempotency_marker(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('database offline')):
            with self.assertRaises(RuntimeError):
                import_contacts(self.payload())
        self.assertEqual(ContactLead.query.count(), 0)
        self.assertEqual(ContactImportEvent.query.count(), 0)
        self.assertEqual(import_contacts(self.payload())['created'], 1)

    def test_manual_create_and_edit_refuse_existing_phone(self):
        import_contacts(self.payload())
        other = ContactLead(name='Outro', phone='45988887777', confirmation_code='887766')
        db.session.add(other)
        db.session.commit()
        for contact_id in ('', str(other.id)):
            response = self.client.post('/admin/contatos', data={'csrf_token': 'csrf-test', 'name': 'Renomear',
                'phone': '(45) 99999-1234', 'tag': 'nova', 'contact_id': contact_id})
            self.assertEqual(response.status_code, 302)
            self.assertIn('edit=', response.location)
        self.assertEqual(ContactLead.query.count(), 2)
        self.assertEqual(ContactLead.query.filter_by(name='Ana').count(), 1)
        self.assertEqual(other.phone, '45988887777')

    def test_formatted_manual_phone_and_validation_preserve_form(self):
        response = self.client.post('/admin/contatos', data={'csrf_token': 'csrf-test', 'name': 'Maria', 'phone': '(45) 99999-1234'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContactLead.query.first().phone, '5545999991234')
        response = self.client.post('/admin/contatos', data={'csrf_token': 'csrf-test', 'name': 'Manter este nome', 'phone': '123'})
        self.assertEqual(response.status_code, 422)
        self.assertIn(b'Manter este nome', response.data)

    def test_csrf_and_admin_access_required(self):
        self.assertEqual(self.client.post('/admin/contatos', data={'name': 'Ana', 'phone': '45999991234'}).status_code, 400)
        self.assertEqual(self.client.post('/admin/contatos/whatsapp/configurar', data={'action': 'pause'}).status_code, 400)
        anonymous = self.app.test_client()
        for url in ('/admin/contatos', '/admin/contatos/whatsapp/grupos', '/admin/contatos/whatsapp/status'):
            with self.app.app_context():
                self.assertEqual(anonymous.get(url).status_code, 302)

    def test_selection_verified_pause_and_activation_date(self):
        before = db.session.get(ContactImportSettings, 1).activated_at
        with patch('app.admin.routes._bridge_request', return_value={'groups': [{'id': '123@g.us', 'name': 'Convidados'}, {'id': '456@g.us', 'name': 'Novo grupo'}]}):
            for group in ('123@g.us', 'not-found@g.us'):
                self.client.post('/admin/contatos/whatsapp/configurar', data={'csrf_token': 'csrf-test', 'group_jid': group})
                self.assertEqual(db.session.get(ContactImportSettings, 1).activated_at, before)
            self.client.post('/admin/contatos/whatsapp/configurar', data={'csrf_token': 'csrf-test', 'group_jid': '456@g.us'})
            self.assertGreater(db.session.get(ContactImportSettings, 1).activated_at, before)
        self.client.post('/admin/contatos/whatsapp/configurar', data={'csrf_token': 'csrf-test', 'action': 'pause'})
        self.assertFalse(db.session.get(ContactImportSettings, 1).enabled)

    def test_search_pagination_tags_and_status(self):
        for index in range(31):
            db.session.add(ContactLead(name=f'Pessoa {index:02}', phone=f'554599999{index:04}', tag='família' if index < 5 else 'amigos'))
        db.session.commit()
        response = self.client.get('/admin/contatos')
        self.assertIn(b'Pr\xc3\xb3xima', response.data)
        self.assertIn(b'P\xc3\xa1gina 1 de 2', response.data)
        self.assertIn(b'Pessoa 00', self.client.get('/admin/contatos?q=Pessoa+00').data)
        self.assertNotIn(b'Pessoa 00', self.client.get('/admin/contatos?tag=amigos').data)
        self.assertIn(b'Pessoa 00', self.client.get('/admin/contatos?q=%2845%29+99999-0000').data)
        with patch('app.admin.routes._bridge_request', return_value={'ready': True, 'pending': 0, 'retrying': 0}):
            self.assertEqual(self.client.get('/admin/contatos/whatsapp/status').json['total'], 31)

    def test_international_phone_survives_normalization_and_send(self):
        phone = clean_phone('+1 (202) 555-0123')
        self.assertEqual(phone, '+12025550123')
        self.assertEqual(phone_key(phone), '12025550123')
        self.assertEqual(normalize_whatsapp_phone(phone), '12025550123')
        self.assertEqual(format_phone(phone), phone)
        self.assertEqual(format_phone('554533331234'), '+55 (45) 3333-1234')
        with patch('app.services.whatsapp._bridge_request', return_value={'messageId': '1'}) as request:
            _post_send_text(phone, 'Teste')
            self.assertEqual(request.call_args.args[2]['phone'], '+12025550123')


if __name__ == '__main__':
    unittest.main()
