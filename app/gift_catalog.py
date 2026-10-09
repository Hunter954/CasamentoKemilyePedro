"""One-time additive catalog release; preserves gifts managed in the admin."""
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import GiftCatalogRelease, GiftItem

RELEASE_KEY = 'gift-storefront-2026-10'
INITIAL_GIFTS = [
    {
        "title": "Café da manhã a dois",
        "description": "Um despertar especial para começarmos nossa nova vida juntos.",
        "price": 89.9,
        "image_url": "/static/images/gifts/breakfast.jpg"
    },
    {
        "title": "Jantar romântico",
        "description": "Uma noite especial, cheia de boas conversas e novas memórias.",
        "price": 189.9,
        "image_url": "/static/images/gifts/dinner.jpg"
    },
    {
        "title": "Kit para nosso novo lar",
        "description": "Um carinho para deixar nossa casinha ainda mais acolhedora.",
        "price": 149.9,
        "image_url": "/static/images/gifts/home.jpg"
    },
    {
        "title": "Passeio na lua de mel",
        "description": "Uma experiência inesquecível para nossa primeira viagem de casados.",
        "price": 259.9,
        "image_url": "/static/images/gifts/travel.jpg"
    },
    {
        "title": "Noite de cinema",
        "description": "Pipoca, filme e momentos divertidos para viver lado a lado.",
        "price": 69.9,
        "image_url": "/static/images/gifts/cinema.jpg"
    },
    {
        "title": "Brinde aos recém-casados",
        "description": "Um brinde ao amor e a todos os nossos próximos capítulos.",
        "price": 119.9,
        "image_url": "/static/images/gifts/wine.jpg"
    }
]
ADDITIONAL_GIFTS = [
    {
        "title": "Um café com carinho",
        "description": "Uma pausa gostosa para conversar e aproveitar a vida a dois.",
        "price": 49.9,
        "image_url": "/static/images/gifts/coffee.jpg"
    },
    {
        "title": "Doce começo",
        "description": "Uma sobremesa especial para adoçar nossos primeiros dias de casados.",
        "price": 79.9,
        "image_url": "/static/images/gifts/dessert.jpg"
    },
    {
        "title": "Verde para nossa casa",
        "description": "Plantas e pequenos cuidados para encher nosso lar de vida.",
        "price": 99.9,
        "image_url": "/static/images/gifts/plants.jpg"
    },
    {
        "title": "Receita de amor",
        "description": "Utensílios para preparar receitas e descobrir novos sabores juntos.",
        "price": 159.9,
        "image_url": "/static/images/gifts/kitchen.jpg"
    },
    {
        "title": "Cantinho do café",
        "description": "Um carinho para montar o lugar das nossas conversas de todos os dias.",
        "price": 199.9,
        "image_url": "/static/images/gifts/coffee-corner.jpg"
    },
    {
        "title": "Noites aconchegantes",
        "description": "Roupa de cama para trazer conforto e carinho ao nosso novo lar.",
        "price": 229.9,
        "image_url": "/static/images/gifts/bedroom.jpg"
    },
    {
        "title": "Detalhes para nossa cozinha",
        "description": "Pequenos utensílios para preparar refeições e cuidar do nosso novo lar.",
        "price": 279.9,
        "image_url": "/static/images/gifts/table.jpg"
    },
    {
        "title": "Nosso lar, nosso jeito",
        "description": "Detalhes de decoração para deixar a casa com a nossa personalidade.",
        "price": 299.9,
        "image_url": "/static/images/gifts/living.jpg"
    },
    {
        "title": "Dia de spa a dois",
        "description": "Uma pausa para relaxar e aproveitar a companhia um do outro.",
        "price": 349.9,
        "image_url": "/static/images/gifts/spa.jpg"
    },
    {
        "title": "Escapada à beira-mar",
        "description": "Um passeio para sentir a brisa e colecionar memórias na lua de mel.",
        "price": 399.9,
        "image_url": "/static/images/gifts/beach.jpg"
    },
    {
        "title": "Uma estadia especial",
        "description": "Uma contribuição para uma noite inesquecível da nossa lua de mel.",
        "price": 599.9,
        "image_url": "/static/images/gifts/hotel.jpg"
    },
    {
        "title": "Viagem dos nossos sonhos",
        "description": "Um carinho para nos ajudar a viver novas aventuras como casal.",
        "price": 899.9,
        "image_url": "/static/images/gifts/mountains.jpg"
    }
]


def seed_gift_catalog():
    """Add this release once without editing existing gifts or purchases."""
    if db.session.get(GiftCatalogRelease, RELEASE_KEY):
        return 0
    try:
        # Claim the release in the same transaction as the gift inserts.
        db.session.add(GiftCatalogRelease(key=RELEASE_KEY))
        db.session.flush()
        existing = {title.strip().casefold() for (title,) in db.session.query(GiftItem.title).all()}
        catalog = ADDITIONAL_GIFTS if existing else INITIAL_GIFTS + ADDITIONAL_GIFTS
        added = 0
        for item in catalog:
            if item['title'].strip().casefold() in existing:
                continue
            db.session.add(GiftItem(**item, active=True, allow_multiple_purchases=True))
            existing.add(item['title'].strip().casefold())
            added += 1
        db.session.commit()
        return added
    except IntegrityError:
        db.session.rollback()
        if db.session.get(GiftCatalogRelease, RELEASE_KEY):
            return 0
        raise
