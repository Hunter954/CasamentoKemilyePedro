import re
from datetime import date
from app import db
from app.models import Ceremony, FAQ, ContentRelease, SiteSettings, CampaignDelivery


def seed_site_content():
    if not db.session.get(CampaignDelivery, 1):
        db.session.add(CampaignDelivery(id=1, interval_seconds=15))
    if not db.session.get(ContentRelease, 'ceremonies-faq-v1'):
        settings = SiteSettings.query.first()
        raw_time = settings.wedding_time if settings else ''
        match = re.fullmatch(r'(\d{1,2})[h:](\d{2})', raw_time or '')
        event_time = f'{int(match[1]):02}:{match[2]}' if match and int(match[1]) < 24 and int(match[2]) < 60 else ''
        event_date = settings.wedding_date.date() if settings and settings.wedding_date else date(2026, 12, 11)
        if not Ceremony.query.count():
            venue = settings.wedding_location_name if settings and settings.wedding_location_name not in ('Espaço do Casamento', '') else 'Paróquia Nossa Senhora de Fátima'
            address = settings.wedding_address if settings and settings.wedding_address != 'Endereço do evento' else 'R. Exemplo, 123 – Centro'
            city = settings.wedding_city if settings and settings.wedding_city != 'Cidade/UF' else 'Sua Cidade - UF'
            db.session.add(Ceremony(kind='church', title='Cerimônia religiosa', venue=venue,
                                   address=address, city=city, event_date=event_date, event_time=event_time,
                                   route_url=settings.route_url if settings else ''))
            db.session.add(Ceremony(kind='party', title='Recepção e celebração', venue='Espaço Porto Dourado',
                                   address='Av. Exemplo, 456 – Bairro', city='Sua Cidade - UF', event_date=event_date))
        if not FAQ.query.count():
            defaults = [
                ('Posso levar acompanhante?', 'Consulte o convite recebido, pois nele estará indicada a quantidade de pessoas incluídas no seu convite.'),
                ('Qual o traje sugerido?', 'Traje social leve / esporte fino. Escolha algo confortável e elegante para celebrar conosco.'),
                ('Haverá estacionamento?', 'As informações de estacionamento serão disponibilizadas junto às orientações de cada local.'),
                ('Crianças são bem-vindas?', 'Sim. Para organização, pedimos apenas que elas sejam incluídas na confirmação de presença.'),
                ('Como confirmar minha presença?', 'Clique em “Confirmar presença” para acessar a página dedicada e concluir sua confirmação.'),
            ]
            db.session.add_all([FAQ(question=q, answer=a, position=i) for i, (q, a) in enumerate(defaults)])
        db.session.add(ContentRelease(key='ceremonies-faq-v1'))
    db.session.commit()
