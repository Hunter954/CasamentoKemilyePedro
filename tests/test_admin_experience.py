import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['WA_DISABLE_AUTO_START'] = 'true'
from app import create_app, db, _sync_schema
from app.models import (AdminUser, SiteSettings, ContactLead, WhatsAppCampaign,
                        WhatsAppDispatch, CampaignJob, FAQ, GuestbookMessage, GiftPurchase)
from app.services.invitations import record_invitation_response
from app.services.campaign_queue import queue_campaign, process_next
from app.services.campaign_audience import audience_contacts


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
        self.assertEqual(CampaignJob.query.count(), before)
        self.assertEqual(queue_campaign(copy, 'https://example.test'), 1)

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
        _sync_schema(self.app); _sync_schema(self.app)
        self.assertEqual(self.campaign.target_rsvp, 'pending')


if __name__ == '__main__':
    unittest.main()
