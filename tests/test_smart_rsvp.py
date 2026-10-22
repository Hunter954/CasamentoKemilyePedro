import os
import unittest
from datetime import datetime
from unittest.mock import patch
from flask import g

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
os.environ.pop('ADMIN_EMAIL', None)
os.environ.pop('ADMIN_PASSWORD', None)

from app import create_app, db
from app.models import ContactLead, RSVP, AdminUser, WhatsAppCampaign, CampaignJob
from app.guest_counts import invitation_names
from app.services.invitations import invitation_report
from app.services.campaign_queue import queue_campaign, process_next


class SmartRSVPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='smart-rsvp-test-only')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def contact(self, name='Kevin & Anita & BB', code='123456'):
        item = ContactLead(name=name, phone='45999991234', email='private@example.test',
                           confirmation_code=code, tag='familia')
        db.session.add(item)
        db.session.commit()
        return item

    def open(self, code='123456', client=None):
        client = client or self.client
        return client.get('/?codigo=' + code, follow_redirects=True)

    def reply(self, attendance='yes', client=None, **extra):
        client = client or self.client
        with client.session_transaction() as state:
            token = state.get('rsvp_csrf', '')
        return client.post('/rsvp', data={'action': 'reply', 'csrf_token': token,
                                         'attendance': attendance, **extra}, follow_redirects=True)

    def test_counts_only_nonempty_ampersand_segments(self):
        examples = {'Kevin': 1, 'Kevin & Anita': 2, 'Kevin & Anita & BB': 3,
                    'Kevin & Anita & BB & Thomas': 4, 'Maria & João & Pedro & Ana & Lucas': 5,
                    '  Kevin  &  Anita &  & BB & ': 3, 'Ana e João, Pedro': 1, '&& ': 0}
        for name, total in examples.items():
            self.assertEqual(len(invitation_names(name)), total)

    def test_valid_one_two_three_person_links_prefill_without_writing(self):
        for index, name in enumerate(('Kevin', 'Kevin & Anita', 'Kevin & Anita & BB'), 1):
            code = '12345' + str(index)
            self.contact(name, code)
            response = self.open(code)
            html = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn('readonly', html)
            self.assertIn(f'value="{code}"', html)
            self.assertIn(f'{index} ' + ('pessoa' if index == 1 else 'pessoas'), html)
            self.assertNotIn('name="guests_count"', html)
            self.assertNotIn('private@example.test', html)
            self.assertNotIn('45999991234', html)
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
            self.assertEqual(RSVP.query.count(), 0)

    def test_bad_unknown_and_duplicate_codes_allow_manual_entry(self):
        self.contact()
        for code in ('hello', '123456abc', '000000', '123', '1' * 21):
            html = self.open(code).get_data(as_text=True)
            self.assertIn('Não encontramos esse convite', html)
            self.assertIn('Encontrar meu convite', html)
            self.assertNotIn('Kevin', html)
        self.contact('Outra pessoa', '123456')
        self.assertIn('Não encontramos esse convite', self.open().get_data(as_text=True))
        self.assertEqual(RSVP.query.count(), 0)

    def test_accept_uses_official_names_count_and_ignores_forged_fields(self):
        contact = self.contact(' Kevin &  Anita & & BB ')
        self.open()
        response = self.reply(guest_name='Atacante', name='Novo nome', guests_count='999999', contact_id='999')
        record = RSVP.query.one()
        self.assertEqual((record.guest_name, record.guests_count, record.attendance), (contact.name, 3, 'yes'))
        self.assertEqual(contact.name, ' Kevin &  Anita & & BB ')
        self.assertEqual(ContactLead.query.count(), 1)
        self.assertIn('3 pessoas confirmadas', response.get_data(as_text=True))
        self.assertIn('11 de dezembro de 2026', response.get_data(as_text=True))

    def test_decline_whole_group_reports_three_absences(self):
        self.contact()
        self.open()
        response = self.reply('no', guests_count='garbage')
        record = RSVP.query.one()
        self.assertEqual((record.attendance, record.guests_count), ('no', 0))
        _, _, totals = invitation_report()
        self.assertEqual((totals['no'], totals['yes'], totals['pending']), (3, 0, 0))
        self.assertIn('3 pessoas não comparecerão', response.get_data(as_text=True))

    def test_repeated_clicks_devices_reload_and_existing_status_are_idempotent(self):
        self.contact()
        self.open()
        self.reply()
        record = RSVP.query.one()
        before = (record.id, record.confirmed_at, record.updated_at)
        for _ in range(3):
            self.reply('no')
        other = self.app.test_client()
        self.open(client=other)
        self.reply(client=other)
        db.session.expire_all()
        self.assertEqual(RSVP.query.count(), 1)
        self.assertEqual((record.id, record.confirmed_at, record.updated_at), before)
        self.assertEqual(record.attendance, 'yes')
        self.assertIn('Presença confirmada!', self.client.get('/rsvp').get_data(as_text=True))

    def test_no_automatic_reply_for_link_previews_or_whatsapp_user_agent(self):
        self.contact()
        for ua in ('facebookexternalhit/1.1', 'WhatsApp/2.24.6.77 A',
                   'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Version/4.0 Chrome/122 Mobile Safari/537.36 WhatsApp/2.24'):
            response = self.client.get('/?codigo=123456', headers={'User-Agent': ua}, follow_redirects=True)
            self.assertIn('Confirmar presença', response.get_data(as_text=True))
        self.assertEqual(RSVP.query.count(), 0)

    def test_manual_lookup_and_site_without_code(self):
        self.contact()
        self.assertIn('Encontrar meu convite', self.client.get('/rsvp').get_data(as_text=True))
        with self.client.session_transaction() as state:
            token = state['rsvp_csrf']
        response = self.client.post('/rsvp', data={'action': 'lookup', 'csrf_token': token,
                                      'confirmation_code': '123456'}, follow_redirects=True)
        self.assertIn('Kevin &amp; Anita &amp; BB', response.get_data(as_text=True))
        self.assertEqual(RSVP.query.count(), 0)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_requires_session_credential_csrf_and_valid_choice(self):
        contact = self.contact()
        self.client.get('/rsvp')
        self.reply(confirmation_code='123456')
        self.assertEqual(RSVP.query.count(), 0)
        self.open()
        self.client.post('/rsvp', data={'action': 'reply', 'attendance': 'yes'})
        self.reply('maybe')
        self.assertEqual(RSVP.query.count(), 0)
        contact.confirmation_code = '654321'
        db.session.commit()
        self.reply()
        self.assertEqual(RSVP.query.count(), 0)

    def test_admin_name_corrections_update_counts_without_rewriting_history(self):
        contact = self.contact('Kevin')
        self.open()
        self.reply()
        record = RSVP.query.one()
        contact.name = 'Kevin & Anita & BB'
        db.session.commit()
        rows, _, totals = invitation_report()
        self.assertEqual((rows[0]['people'], totals['yes'], totals['no']), (3, 1, 2))
        self.assertEqual((record.guests_count, record.guest_name), (1, 'Kevin'))

    def test_admin_report_separates_pending_accepted_declined_and_historical_records(self):
        a = self.contact('A & B & C', '111111')
        self.open('111111'); self.reply()
        self.contact('D & E & F', '222222')
        self.open('222222'); self.reply('no')
        self.contact('G & H', '333333')
        db.session.add(RSVP(guest_name='Manual', phone='45999991234', guests_count=4, attendance='yes'))
        admin = AdminUser(name='Admin', email='rsvp@example.test'); admin.set_password('test-only')
        db.session.add(admin); db.session.commit()
        rows, legacy, totals = invitation_report()
        self.assertEqual((totals['yes'], totals['no'], totals['pending'], totals['people']), (7, 3, 2, 12))
        with self.client.session_transaction() as state:
            state['_user_id'] = admin.get_id(); state['_fresh'] = True
        g.pop('_login_user', None)
        html = self.client.get('/admin/confirmacoes').get_data(as_text=True)
        self.assertIn('Não comparecerá', html)
        self.assertIn('Presença confirmada', html)
        self.assertIn('Pendente', html)
        self.assertIn('A &amp; B &amp; C', html)

    def test_personalized_links_in_campaign_caption_and_preview_do_not_send(self):
        contact = self.contact()
        campaign = WhatsAppCampaign(title='Convite', message='Olá %contato% https://kemilyepedro.com.br/?codigo=%codigo%', image_path='/media/convite.jpg', target_tag='todos')
        db.session.add(campaign); db.session.commit()
        self.assertEqual(queue_campaign(campaign, 'https://kemilyepedro.com.br'), 1)
        job = CampaignJob.query.one()
        self.assertEqual(job.kind, 'image')
        self.assertIn('/?codigo=123456', job.message)
        with patch('app.services.campaign_queue.get_instance_status', return_value={'connected': True}), \
             patch('app.services.campaign_queue._post_send_image', return_value={'message_id': 'test-only'}) as send:
            process_next(datetime.utcnow())
            self.assertIn('/?codigo=123456', send.call_args.args[2])
        admin = AdminUser(name='Admin', email='preview@example.test'); admin.set_password('test-only')
        db.session.add(admin); db.session.commit()
        with self.client.session_transaction() as state:
            state['_user_id'] = admin.get_id(); state['_fresh'] = True; state['panel_csrf'] = 'preview-test'
        g.pop('_login_user', None)
        count = CampaignJob.query.count()
        response = self.client.post('/admin/campanhas/previa', data={'csrf_token': 'preview-test',
                    'contact_id': contact.id, 'message': campaign.message})
        self.assertEqual(response.status_code, 200)
        self.assertIn('/?codigo=123456', response.json['message'])
        self.assertNotIn('%codigo%', response.json['message'])
        self.assertEqual(CampaignJob.query.count(), count)

    def test_only_authenticated_admin_can_correct_existing_response(self):
        contact = self.contact()
        self.open(); self.reply()
        record_id = RSVP.query.one().id
        url = f'/admin/confirmacoes/{contact.id}/resposta'
        self.assertEqual(self.client.post(url, data={'attendance': 'no'}).status_code, 302)
        self.assertEqual(RSVP.query.one().attendance, 'yes')
        admin = AdminUser(name='Admin', email='correction@example.test'); admin.set_password('test-only')
        db.session.add(admin); db.session.commit()
        with self.client.session_transaction() as state:
            state['_user_id'] = admin.get_id(); state['_fresh'] = True; state['panel_csrf'] = 'correction-test'
        g.pop('_login_user', None)
        self.assertEqual(self.client.post(url, data={'attendance': 'no'}).status_code, 400)
        self.assertEqual(self.client.post(url, data={'csrf_token': 'correction-test', 'attendance': 'no'}).status_code, 302)
        self.assertEqual(RSVP.query.count(), 1)
        self.assertEqual((RSVP.query.one().id, RSVP.query.one().attendance, RSVP.query.one().guests_count), (record_id, 'no', 0))
        self.assertEqual(invitation_report()[2]['no'], 3)
