import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy import text

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
from app import create_app, db, _sync_schema
from app.models import (AdminUser, SiteSettings, ContactLead, WhatsAppCampaign,
                        WhatsAppDispatch, CampaignJob, FAQ, GuestbookMessage, GiftPurchase)
from app.services.invitations import record_invitation_response
from app.services.campaign_queue import queue_campaign, process_next, queue_overview
from app.services.campaign_audience import audience_contacts
from app.services.reminder_schedule import reminder_plan


class AdminExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, SECRET_KEY='experience-tests-only')

    def setUp(self):
        self.ctx = self.app.app_context(); self.ctx.push()
        db.drop_all(); db.create_all()
        self.admin = AdminUser(name='Teste', email='admin@example.test')
        self.admin.set_password('test-only-password')
        self.pending = ContactLead(name='Ágata & Pedro', phone='5511999991234', tag='família')
        self.yes = ContactLead(name='Zélia', phone='5511999992345', tag='família')
        self.no = ContactLead(name='Bruna', phone='5511999993456', tag='família')
        self.other = ContactLead(name='Carlos', phone='5511999994567', tag='amigos')
        self.campaign = WhatsAppCampaign(title='Lembrete', message='Olá %contato%', target_tag='família', target_rsvp='pending')
        db.session.add_all([self.admin, SiteSettings(), self.pending, self.yes, self.no, self.other, self.campaign])
        db.session.flush()
        record_invitation_response(self.yes, 'yes'); record_invitation_response(self.no, 'no')
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = self.admin.get_id(); session['_fresh'] = True; session['panel_csrf'] = 'csrf-test'

    def tearDown(self):
        db.session.remove(); self.ctx.pop()

    def post(self, path, **data):
        return self.client.post(path, data={'csrf_token':'csrf-test', **data})

    def test_audience_preview_and_queue_use_same_rule(self):
        self.assertEqual([c.id for c in audience_contacts(self.campaign)], [self.pending.id])
        html = self.client.get(f'/admin/campanhas/{self.campaign.id}/publico').get_data(as_text=True)
        self.assertIn('Ágata &amp; Pedro', html)
        self.assertNotIn('Zélia', html)
        self.assertEqual(CampaignJob.query.count(), 0)
        self.assertEqual(queue_campaign(self.campaign, 'https://example.test'), 1)
        self.assertEqual(queue_campaign(self.campaign, 'https://example.test'), 0)
        self.assertEqual(WhatsAppDispatch.query.one().contact_id, self.pending.id)

    def test_answer_before_queue_creation_excludes_guest(self):
        record_invitation_response(self.pending, 'no'); db.session.commit()
        self.assertEqual(queue_campaign(self.campaign, 'https://example.test'), 0)

    def test_answer_while_waiting_cancels_reminder_without_contacting_provider(self):
        queue_campaign(self.campaign, 'https://example.test')
        record_invitation_response(self.pending, 'yes'); db.session.commit()
        with patch('app.services.campaign_queue._post_send_text') as sender, patch('app.services.campaign_queue.get_instance_status') as status:
            self.assertEqual(process_next()['state'], 'cancelled')
            sender.assert_not_called(); status.assert_not_called()
        self.assertEqual(CampaignJob.query.one().status, 'cancelled')

    def test_new_reminder_reuses_content_and_never_starts_sending(self):
        self.campaign.target_rsvp = 'all'; db.session.commit()
        queue_campaign(self.campaign, 'https://example.test')
        before = CampaignJob.query.count()
        self.assertEqual(self.post(f'/admin/campanhas/{self.campaign.id}/lembrete').status_code, 302)
        copy = WhatsAppCampaign.query.order_by(WhatsAppCampaign.id.desc()).first()
        self.assertEqual((copy.target_rsvp, copy.message), ('pending', self.campaign.message))
        self.assertTrue(copy.scheduled_reminder)
        self.assertEqual(CampaignJob.query.count(), before)
        with self.assertRaisesRegex(ValueError, 'Revise a programação'):
            queue_campaign(copy, 'https://example.test')

    def test_reminder_preview_and_queue_follow_first_successful_invite(self):
        now = datetime(2026, 11, 4, 14)
        first_invite = WhatsAppCampaign(title='Convites de outubro', message='Convite')
        second_invite = WhatsAppCampaign(title='Convites de novembro', message='Convite')
        self.campaign.scheduled_reminder = True
        self.campaign.target_tag = 'todos'
        uninvited = ContactLead(name='Sem convite', phone='5511999999876')
        db.session.add_all([first_invite, second_invite, uninvited])
        db.session.flush()
        db.session.add_all([
            WhatsAppDispatch(campaign=first_invite, contact=self.pending, status='read', sent_at=now - timedelta(days=8)),
            WhatsAppDispatch(campaign=second_invite, contact=self.pending, status='sent', sent_at=now - timedelta(hours=2)),
            WhatsAppDispatch(campaign=first_invite, contact=self.other, status='error', sent_at=now - timedelta(days=8)),
            WhatsAppDispatch(campaign=second_invite, contact=self.other, status='sent', sent_at=now - timedelta(hours=2)),
            WhatsAppDispatch(campaign=first_invite, contact=self.yes, status='sent', sent_at=now - timedelta(days=8)),
        ])
        db.session.commit()
        source_ids = [first_invite.id, second_invite.id]
        rows, deadline = reminder_plan(self.campaign, source_ids, 24, '2026-11-04', now=now)
        self.assertEqual(deadline, datetime(2026, 11, 5, 3))
        self.assertEqual([row['state'] for row in rows], ['ready', 'expired', 'missing'])
        url = f'/admin/campanhas/{self.campaign.id}'
        with patch('app.services.reminder_schedule.datetime', wraps=datetime) as schedule_clock, \
             patch('app.services.campaign_queue.datetime', wraps=datetime) as queue_clock:
            schedule_clock.utcnow.return_value = queue_clock.utcnow.return_value = now
            html = self.client.get(f'{url}/publico').get_data(as_text=True)
            self.assertIn('27/10/2026 às 11:00', html)
            self.assertIn('05/11/2026 às 09:00', html)
            self.assertNotIn('Zélia', html)
            self.assertEqual(CampaignJob.query.count(), 0)
            form = dict(source_ids=source_ids, wait_hours='24', deadline='2026-11-05')
            self.post(f'{url}/disparar', **form)
            self.post(f'{url}/disparar', **form)
            stats = queue_overview()[self.campaign.id]
            self.assertEqual((stats['ready'], stats['scheduled']), (1, 1))
        self.assertEqual(CampaignJob.query.count(), 2)
        with patch('app.services.campaign_queue.get_instance_status', return_value={'connected': True}), \
             patch('app.services.campaign_queue._post_send_text', return_value={'message_id': 'fake'}) as send:
            self.assertEqual(process_next(now)['state'], 'sent')
            self.assertEqual(send.call_args.args[0], self.pending.phone)
            self.assertEqual(process_next(now + timedelta(hours=21))['state'], 'idle')
            record_invitation_response(self.other, 'yes'); db.session.commit()
            self.assertEqual(process_next(now + timedelta(hours=22))['state'], 'cancelled')
            self.assertEqual(send.call_count, 1)

    def test_reminder_expiry_cancels_queue_even_when_paused_or_disconnected(self):
        now = datetime.utcnow()
        queue_campaign(self.campaign, 'https://example.test')
        dispatch = WhatsAppDispatch.query.one()
        dispatch.scheduled_at = now - timedelta(hours=1)
        dispatch.expires_at = now
        self.campaign.queue_paused = True
        db.session.commit()
        with patch('app.services.campaign_queue.get_instance_status') as status:
            process_next(now)
            status.assert_not_called()
        self.assertEqual(dispatch.jobs[0].status, 'cancelled')
        self.assertIn('prazo de envio terminou', dispatch.error_message)

    def test_all_pages_render_with_existing_records(self):
        db.session.add(GuestbookMessage(author_name="Ana D'Ávila", message='Muito amor <3', approved=True))
        db.session.add(GiftPurchase(buyer_name='Ana', buyer_email='ana@example.test', buyer_phone='5511999998888', amount=100, status='approved'))
        db.session.add(FAQ(question='Qual o traje?', answer='Esporte fino', position=0, active=True)); db.session.commit()
        with patch('app.admin.routes.get_instance_status', return_value={'connected':False}):
            for path in ['/admin/confirmacoes','/admin/compras','/admin/mural','/admin/perguntas-frequentes','/admin/campanhas','/mural','/']:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn('K + P', response.get_data(as_text=True))

    def test_moderation_is_post_only_and_requires_csrf(self):
        item = GuestbookMessage(author_name='Ana', message='Felicidades!', approved=False)
        db.session.add(item); db.session.commit()
        url = f'/admin/mural/{item.id}/aprovar'
        self.client.get(url); self.assertFalse(item.approved)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.post(url); self.assertTrue(item.approved)

    def test_faq_moves_and_visibility_preserve_content(self):
        a = FAQ(question='Primeira?', answer='Resposta A', position=0)
        b = FAQ(question='Segunda?', answer='Resposta B', position=0)
        db.session.add_all([a,b]); db.session.commit()
        self.post(f'/admin/perguntas-frequentes/{b.id}/acao', action='up')
        self.assertEqual([f.id for f in FAQ.query.order_by(FAQ.position, FAQ.id)], [b.id,a.id])
        self.post(f'/admin/perguntas-frequentes/{b.id}/acao', action='toggle')
        self.assertFalse(b.active); self.assertEqual(b.answer, 'Resposta B')

    def test_schema_sync_is_repeatable(self):
        for table, name in [('whatsapp_campaign', 'scheduled_reminder'), ('whatsapp_dispatch', 'scheduled_at'),
                            ('whatsapp_dispatch', 'expires_at')]:
            db.session.execute(text(f'ALTER TABLE {table} DROP COLUMN {name}'))
        db.session.commit()
        _sync_schema(self.app); _sync_schema(self.app)
        self.assertEqual(self.campaign.target_rsvp, 'pending')
        self.assertFalse(self.campaign.scheduled_reminder)


if __name__ == '__main__':
    unittest.main()
