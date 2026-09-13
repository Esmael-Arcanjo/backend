"""Seed 30 demo products for the marketplace. Idempotent — runs on startup.
Products are attached to a demo seller `demo.seller@wibaza.com`."""
import logging
from datetime import datetime, timezone

from app.core.database import db
from app.core.security import hash_password

logger = logging.getLogger("leamse.mp.seed_products")

DEMO_SELLER_EMAIL = "demo.seller@wibaza.com"
DEMO_SELLER_PASSWORD = "DemoSeller2026!"
DEMO_STORE_NAME = "Wibaza Store"
DEMO_STORE_SLUG = "wibaza-store"


CATEGORIES = {
    "Moda Feminina": {
        "sizes": ["PP", "P", "M", "G", "GG"],
        "colors": ["Preto", "Branco", "Azul", "Rosa", "Vermelho"],
        "items": [
            ("Vestido Midi Floral", "Vestido midi em tecido leve com estampa floral exclusiva. Ideal para o dia a dia e ocasiões especiais.", 12990),
            ("Blusa Canelada Básica", "Blusa canelada com decote redondo. Malha de alta gramatura, super confortável.", 6990),
            ("Calça Wide Leg", "Calça wide leg de alfaiataria com cintura alta. Modelagem que valoriza a silhueta.", 15990),
            ("Jaqueta Jeans Oversized", "Jaqueta jeans oversized com lavagem estonada. Peça-chave para looks descontraídos.", 18990),
        ],
    },
    "Moda Masculina": {
        "sizes": ["P", "M", "G", "GG", "XG"],
        "colors": ["Preto", "Branco", "Cinza", "Verde", "Azul Marinho"],
        "items": [
            ("Camiseta Pima Regular", "Camiseta em algodão Pima 100%. Toque macio, caimento perfeito e durabilidade superior.", 8990),
            ("Bermuda Sarja Chino", "Bermuda em sarja com cinco bolsos. Modelagem chino, ideal para o verão.", 11990),
            ("Camisa Linho Manga Longa", "Camisa em linho puro com botões de madeira. Elegância e frescor em uma só peça.", 19990),
            ("Tênis Casual Couro", "Tênis casual em couro legítimo com solado de borracha. Combina com jeans e alfaiataria.", 29990),
        ],
    },
    "Casa & Decoração": {
        "sizes": ["Único"],
        "colors": ["Bege", "Branco", "Preto", "Verde"],
        "items": [
            ("Vaso Cerâmica Artesanal", "Vaso feito à mão por ceramistas de Minas Gerais. Cada peça é única.", 14900),
            ("Manta Tricô Natural", "Manta em tricô com fio natural, 130x180cm. Traz aconchego para o sofá.", 22990),
            ("Luminária LED Dourada", "Luminária de mesa com base dourada e cúpula em linho bege. Luz quente 3000K.", 34990),
            ("Kit 3 Quadros Botânicos", "Kit com três quadros botânicos emoldurados em madeira. 30x40cm cada.", 12990),
        ],
    },
    "Eletrônicos": {
        "sizes": ["Único"],
        "colors": ["Preto", "Branco", "Prata"],
        "items": [
            ("Fone Bluetooth ANC", "Fone com cancelamento ativo de ruído, 30h de bateria e som Hi-Res.", 49900),
            ("Smartwatch Fitness Pro", "Monitoramento de saúde 24/7, GPS integrado e mais de 100 modos esportivos.", 89900),
            ("Speaker Bluetooth Portátil", "Caixa de som portátil, à prova d'água IPX7, com 20h de bateria.", 39900),
            ("Câmera de Segurança 2K", "Câmera Wi-Fi 2K com visão noturna, detecção IA e áudio bidirecional.", 24990),
        ],
    },
    "Beleza": {
        "sizes": ["Único"],
        "colors": ["Único"],
        "items": [
            ("Sérum Vitamina C 30ml", "Sérum concentrado com 15% de vitamina C. Ilumina e uniformiza a pele.", 8990),
            ("Máscara Capilar Reparadora 500g", "Máscara com óleo de argan e queratina para cabelos danificados.", 6990),
            ("Kit Skincare Rotina Completa", "Kit com sabonete, tônico, sérum e hidratante. Para todos os tipos de pele.", 24990),
            ("Perfume Floral 100ml", "Perfume floral amadeirado, longa fixação, embalagem premium.", 34900),
        ],
    },
    "Esportes": {
        "sizes": ["P", "M", "G", "GG"],
        "colors": ["Preto", "Cinza", "Azul", "Vermelho"],
        "items": [
            ("Tênis Running Amortecimento", "Tênis para corrida com solado responsivo e cabedal respirável.", 39990),
            ("Legging Fitness Cintura Alta", "Legging em poliamida com cintura alta e bolso lateral. Compressão média.", 12990),
            ("Kettlebell 12kg", "Kettlebell em ferro fundido com revestimento antiderrapante.", 15990),
            ("Bola de Yoga 65cm", "Bola suíça 65cm antiestouro, suporta até 250kg. Inclui bomba.", 8990),
        ],
    },
    "Livros": {
        "sizes": ["Único"],
        "colors": ["Único"],
        "items": [
            ("O Poder do Hábito", "Charles Duhigg — Best-seller sobre a ciência da formação de hábitos.", 4990),
            ("Sapiens: Uma Breve História", "Yuval Harari — Do surgimento do Homo sapiens até os dias atuais.", 5990),
            ("Mindset: A Nova Psicologia", "Carol Dweck — Como a mentalidade pode mudar a sua vida.", 4590),
            ("Atomic Habits", "James Clear — Pequenas mudanças, resultados extraordinários.", 5490),
        ],
    },
    "Alimentos": {
        "sizes": ["250g", "500g", "1kg"],
        "colors": ["Único"],
        "items": [
            ("Café Especial Torrado 500g", "Café 100% arábica, torra média, notas de chocolate e caramelo.", 4990),
            ("Chocolate 70% Cacau", "Chocolate amargo artesanal, origem única, embalagem sustentável.", 3990),
        ],
    },
}


def _picsum(seed: str, i: int = 0) -> str:
    return f"https://picsum.photos/seed/wibaza-{seed}-{i}/800/800"


async def seed_demo_products() -> None:
    seller = await db.mp_users.find_one({"email": DEMO_SELLER_EMAIL})
    if not seller:
        seller_doc = {
            "email": DEMO_SELLER_EMAIL, "name": "Wibaza Store",
            "password_hash": hash_password(DEMO_SELLER_PASSWORD),
            "user_type": "seller", "store_name": DEMO_STORE_NAME,
            "slug": DEMO_STORE_SLUG, "bio": "Curadoria Wibaza — produtos com qualidade e entrega garantida.",
            "banner_url": _picsum("banner", 0),
            "created_at": datetime.now(timezone.utc),
        }
        r = await db.mp_users.insert_one(seller_doc)
        seller = {**seller_doc, "_id": r.inserted_id}
        logger.info("MP demo seller seeded: %s", DEMO_SELLER_EMAIL)
    seller_id = str(seller["_id"])

    total_desired = sum(len(v["items"]) for v in CATEGORIES.values())
    existing = await db.mp_products.count_documents({"seller_id": seller_id, "demo": True})
    if existing >= total_desired:
        return

    idx = 0
    for category, cfg in CATEGORIES.items():
        for name, description, price in cfg["items"]:
            idx += 1
            slug_seed = name.lower().replace(" ", "-")
            existing_prod = await db.mp_products.find_one({"seller_id": seller_id, "name": name})
            if existing_prod:
                continue
            images = [_picsum(slug_seed, i) for i in range(10)]
            await db.mp_products.insert_one({
                "seller_id": seller_id, "seller_name": DEMO_STORE_NAME,
                "seller_slug": DEMO_STORE_SLUG,
                "name": name, "description": description,
                "price_cents": price, "currency": "BRL", "stock": 25,
                "image_url": images[0], "images": images,
                "category": category, "sizes": cfg["sizes"], "colors": cfg["colors"],
                "active": True, "demo": True,
                "created_at": datetime.now(timezone.utc),
            })
    logger.info("MP demo products seeded (%d added)", idx)
