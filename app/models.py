from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdminUser(UserMixin, TimestampMixin, db.Model):
    __tablename__ = 'admin_user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class SiteSettings(TimestampMixin, db.Model):
    __tablename__ = 'site_settings'
    id = db.Column(db.Integer, primary_key=True)
    couple_names = db.Column(db.String(180), default='Kemily & Pedro')
    hero_phrase = db.Column(db.String(255), default='Um grande amor merece ser celebrado com quem faz parte da nossa história.')
    wedding_date = db.Column(db.DateTime, nullable=True)
    wedding_location_name = db.Column(db.String(180), default='Espaço do Casamento')
    wedding_address = db.Column(db.String(255), default='Endereço do evento')
    wedding_city = db.Column(db.String(120), default='Cidade/UF')
    wedding_time = db.Column(db.String(50), default='17h00')
    map_embed_url = db.Column(db.Text, default='')
    route_url = db.Column(db.String(255), default='')
    hero_image = db.Column(db.String(255), default='')
    gift_banner_image = db.Column(db.String(255), default='')
    gift_banner_title = db.Column(db.String(180), default='Presentes')
    gift_button_label = db.Column(db.String(80), default='Ver lista de presentes')
    final_message = db.Column(db.Text, default='Contamos com a sua presença!')
    theme_primary = db.Column(db.String(20), default='#7a3144')
    theme_secondary = db.Column(db.String(20), default='#f7d7df')
    theme_accent = db.Column(db.String(20), default='#f14d78')
    allow_guestbook = db.Column(db.Boolean, default=True)
    require_guestbook_approval = db.Column(db.Boolean, default=True)
    whatsapp_message_template = db.Column(db.Text, default='Olá! Estamos muito felizes em compartilhar esse momento com você. Confirme sua presença no nosso site 💖')
    mercado_pago_enabled = db.Column(db.Boolean, default=False)
    mercado_pago_access_token = db.Column(db.Text, default='')
    mercado_pago_public_key = db.Column(db.String(255), default='')
    zapi_enabled = db.Column(db.Boolean, default=False)
    zapi_instance_id = db.Column(db.String(120), default='')
    zapi_token = db.Column(db.String(255), default='')
    zapi_client_token = db.Column(db.String(255), default='')
    zapi_sender_number = db.Column(db.String(40), default='')
    zapi_base_url = db.Column(db.String(255), default='https://api.z-api.io')
    zapi_delay_seconds = db.Column(db.Integer, default=4)


class RSVP(TimestampMixin, db.Model):
    __tablename__ = 'rsvp'
    id = db.Column(db.Integer, primary_key=True)
    guest_name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    guests_count = db.Column(db.Integer, default=1)
    attendance = db.Column(db.String(20), default='yes')
    message = db.Column(db.Text, default='')
    contact_id = db.Column(db.Integer, db.ForeignKey('contact_lead.id'), nullable=True)
    confirmation_code = db.Column(db.String(20), default='', index=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    contact = db.relationship('ContactLead', backref='rsvps')


class GuestbookMessage(TimestampMixin, db.Model):
    __tablename__ = 'guestbook_message'
    id = db.Column(db.Integer, primary_key=True)
    author_name = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)


class GiftItem(TimestampMixin, db.Model):
    __tablename__ = 'gift_item'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, default='')
    price = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(255), default='')
    active = db.Column(db.Boolean, default=True)
    allow_multiple_purchases = db.Column(db.Boolean, default=True)

    @property
    def approved_purchases_count(self):
        return sum(1 for purchase in self.purchases if purchase.status == 'approved')

    @property
    def is_sold_out(self):
        return (not self.allow_multiple_purchases) and self.approved_purchases_count > 0

    @property
    def is_available(self):
        return self.active and not self.is_sold_out


class GiftCatalogRelease(db.Model):
    __tablename__ = 'gift_catalog_release'
    key = db.Column(db.String(80), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class GiftPurchase(TimestampMixin, db.Model):
    __tablename__ = 'gift_purchase'
    id = db.Column(db.Integer, primary_key=True)
    gift_id = db.Column(db.Integer, db.ForeignKey('gift_item.id'), nullable=True)
    gift = db.relationship('GiftItem', backref='purchases')
    buyer_name = db.Column(db.String(180), nullable=False)
    buyer_email = db.Column(db.String(120), nullable=False)
    buyer_phone = db.Column(db.String(40), nullable=False)
    confirmed_presence = db.Column(db.Boolean, default=False)
    message = db.Column(db.Text, default='')
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default='pending')
    mercado_pago_preference_id = db.Column(db.String(120), default='')
    mercado_pago_payment_id = db.Column(db.String(120), default='')


class ContactLead(TimestampMixin, db.Model):
    __tablename__ = 'contact_lead'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(120), default='')
    tag = db.Column(db.String(80), default='convidado')
    confirmation_code = db.Column(db.String(20), default='', index=True)


class WhatsAppCampaign(TimestampMixin, db.Model):
    __tablename__ = 'whatsapp_campaign'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    active = db.Column(db.Boolean, default=True)
    target_tag = db.Column(db.String(80), default='todos')
    image_path = db.Column(db.String(255), default='')


class WhatsAppDispatch(TimestampMixin, db.Model):
    __tablename__ = 'whatsapp_dispatch'
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('whatsapp_campaign.id'))
    contact_id = db.Column(db.Integer, db.ForeignKey('contact_lead.id'))
    status = db.Column(db.String(30), default='pending')
    sent_at = db.Column(db.DateTime, nullable=True)
    phone_sent = db.Column(db.String(40), default='')
    provider_message_id = db.Column(db.String(120), default='')
    response_body = db.Column(db.Text, default='')
    error_message = db.Column(db.Text, default='')
    campaign = db.relationship('WhatsAppCampaign', backref='dispatches')
    contact = db.relationship('ContactLead', backref='dispatches')


class WhatsAppWebhookLog(TimestampMixin, db.Model):
    __tablename__ = 'whatsapp_webhook_log'
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(80), default='')
    provider = db.Column(db.String(40), default='baileys')
    external_message_id = db.Column(db.String(120), default='')
    phone = db.Column(db.String(40), default='')
    payload = db.Column(db.Text, default='')
    notes = db.Column(db.Text, default='')
