from app import create_app, db
from app.models import AdminUser, SiteSettings, GiftItem
from datetime import datetime

app = create_app()

with app.app_context():
    db.create_all()

    admin = AdminUser.query.filter_by(email=app.config['ADMIN_EMAIL']).first()
    if not admin:
        admin = AdminUser(email=app.config['ADMIN_EMAIL'], name='Administrador')
        admin.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(admin)

    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings(
            couple_names='Kemily & Pedro',
            hero_phrase='Cada detalhe foi sonhado com amor para viver esse dia com você.',
            wedding_date=datetime(2026, 12, 20, 16, 0),
            wedding_location_name='Villa Romântica',
            wedding_address='Rua das Flores, 100 - Centro',
            wedding_city='Foz do Iguaçu - PR',
            wedding_time='16h00',
            map_embed_url='https://www.google.com/maps?q=Foz%20do%20Igua%C3%A7u&output=embed',
            route_url='https://maps.google.com/?q=Foz%20do%20Igua%C3%A7u',
            gift_banner_title='Seu carinho faz parte do nosso começo',
            gift_button_label='Presentear o casal',
            final_message='Contamos com a sua presença neste momento tão importante das nossas vidas.',
            theme_primary='#7a3144',
            theme_secondary='#f7d7df',
            theme_accent='#f14d78',
            allow_guestbook=True,
            require_guestbook_approval=True,
        )
        db.session.add(settings)

    if GiftItem.query.count() == 0:
        db.session.add_all([
            GiftItem(title='Jantar romântico da lua de mel', description='Ajude com um momento especial da viagem.', price=180.0, image_url='', active=True),
            GiftItem(title='Café da manhã especial', description='Um começo de dia inesquecível para o casal.', price=95.0, image_url='', active=True),
            GiftItem(title='Passeio surpresa', description='Contribua com uma experiência marcante.', price=250.0, image_url='', active=True),
        ])

    db.session.commit()
    print('Seed concluído.')
