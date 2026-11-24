"""
Dev-only: give the preview shop real listings from real Nigerian brands.

WHY THIS EXISTS, AND WHAT CHANGED.

The first version of this seeder wrote eight plausible-sounding products for one
demo shop, and three of them were wrong in a way that is worse than an empty
grid: a "Hardcover Notebook Set" illustrated with a photo of a laptop, and a
"Jollof Rice Combo" illustrated with a photo of fufu and efo riro. A shopper reads
the name and the photo together, and a mismatch makes the whole catalogue look
copy-pasted. So the rule for this file is: **name, price, category and photo all
describe the same thing**, and where a real brand is involved the name, price and
photo come from that brand's own store.

The four shops here are real labels the demo should be recognisable against:

  * Bastilluxe Apparel  — streetwear/luxury, Lagos. Names, prices and photos
    taken from bastilluxeapparel.com (BX25 Jersey ₦30,000, Seraph T-Shirt
    ₦25,000, Puppet T-Shirt ₦25,000, Bum Shorts ₦16,500, Signature Lace-Up
    Skirt ₦20,000).
  * MADEBYLUTHER (MBL)  — streetwear accessories. MBL Midnight Skully and MBL
    Panthera Skully ₦15,000, MBL World Cup Tee ₦30,000, from their Brandify
    storefront.
  * Elex & Co           — handcrafted jewellery. The Cipher Bracelet ₦25,000,
    The Monolith Double Strand Bracelet ₦25,000, Matturi Silver Wave ₦55,000,
    from elexandco.com.
  * SpaceWorm           — carried as an account with no listings yet: spworm.xyz
    no longer resolves (NXDOMAIN) and Instagram serves nothing to a signed-out
    fetch, so there is no product data to copy. Better an empty honest shop than
    invented products under somebody else's name.

Their product photos are downloaded into `app/static/images/brands/` rather than
hot-linked: image CDNs change, and a demo that renders grey rectangles because a
signed URL expired is not a demo. CampusTech's own listings keep their Unsplash
URLs, except the jollof photo, which is a local file because the free-stock one
was of the wrong dish.

This is a SEED, not a fallback — nothing in the app reads it. It upserts by slug,
so re-running applies copy or photo fixes to existing rows instead of skipping
them (the old version refused to touch a non-empty table, which is how a wrong
photo survived three re-runs).

    DATABASE_URL=sqlite+aiosqlite:///./dev_preview.db \\
        ./.venv/Scripts/python.exe scripts/seed_products.py

Run `scripts/dev_preview_sync.py` first — it creates the tables.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./dev_preview.db"

import app.models  # noqa: F401,E402  — registers every mapper before use
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database.session import engine  # noqa: E402
from app.models.organization import Organization, OrganizationStatus, OrganizationType  # noqa: E402
from app.models.product import Product, ProductStatus  # noqa: E402
from app.models.user import AccountStatus, AccountType, User  # noqa: E402

IMG = "/static/images/brands"
U = "https://images.unsplash.com/photo-"
DEFAULT_PASSWORD = "Preview-pass-2026"

# One entry per shop. `products` entries are the exact keys the Product model
# takes, so adding a listing never means editing the loop below.
BRANDS: list[dict] = [
    {
        "username": "bastilluxeapparel",
        "display_name": "Bastilluxe Apparel",
        "bio": "Where street meets timeless luxury.",
        "shop": "Bastilluxe Apparel",
        "slug": "bastilluxe-apparel",
        "state": "Lagos",
        "pickup": "Bastilluxe Studio, Lekki Phase 1, Lagos",
        "delivery": ["Lagos", "Nationwide"],
        "products": [
            {
                "slug": "bastilluxe-bx25-jersey",
                "name": "BX25 Jersey",
                "category": "Fashion",
                "price": 30000,
                "stock": 14,
                "sold_count": 96,
                "popularity": 93,
                "description": "Drop-02 football jersey in bubblegum pink, with the Bastilluxe wordmark across the chest and contrast piping. Relaxed fit, breathable mesh.",
                "tags": ["jersey", "streetwear", "bastilluxe"],
                "image_url": f"{IMG}/bastilluxe-bx25-jersey.jpg",
                "image_alt": "Pink Bastilluxe BX25 jersey laid flat on white",
            },
            {
                "slug": "bastilluxe-seraph-tee",
                "name": "Seraph T-Shirt",
                "category": "Fashion",
                "price": 25000,
                "stock": 22,
                "sold_count": 143,
                "popularity": 91,
                "description": "Heavyweight black tee with the Seraph crest embroidered small on the chest. Boxy cut that holds its shape after a wash.",
                "tags": ["tee", "streetwear", "bastilluxe"],
                "image_url": f"{IMG}/bastilluxe-seraph-tee.jpg",
                "image_alt": "Black Bastilluxe Seraph t-shirt with small chest logo",
            },
            {
                "slug": "bastilluxe-puppet-tee",
                "name": "Puppet T-Shirt",
                "category": "Fashion",
                "price": 25000,
                "stock": 18,
                "sold_count": 71,
                "popularity": 87,
                "description": "Back-print graphic tee in black cotton. The Puppet artwork is screen-printed, so it cracks into the fabric the way a print should.",
                "tags": ["tee", "graphic", "bastilluxe"],
                "image_url": f"{IMG}/bastilluxe-puppet-tee.jpg",
                "image_alt": "Black Bastilluxe Puppet t-shirt with white wordmark",
            },
            {
                "slug": "bastilluxe-bum-shorts",
                "name": "Bum Shorts",
                "category": "Fashion",
                "price": 16500,
                "stock": 26,
                "sold_count": 58,
                "popularity": 80,
                "description": "High-waist shorts in pink stretch fabric with black piping and a drawstring waist. Cut short, made to move.",
                "tags": ["shorts", "bastilluxe"],
                "image_url": f"{IMG}/bastilluxe-bum-shorts.jpg",
                "image_alt": "Pink Bastilluxe bum shorts with drawstring waist",
            },
            {
                "slug": "bastilluxe-lace-up-skirt",
                "name": "Signature Lace-Up Skirt",
                "category": "Fashion",
                "price": 20000,
                "stock": 9,
                "sold_count": 44,
                "popularity": 84,
                "description": "Black mini skirt with a lace-up side panel and the crown crest at the hem. Comes in black, pink, red and blue.",
                "tags": ["skirt", "bastilluxe"],
                "image_url": f"{IMG}/bastilluxe-lace-skirt.png",
                "image_alt": "Black Bastilluxe lace-up mini skirt",
            },
        ],
    },
    {
        "username": "mbl.label",
        "display_name": "MADEBYLUTHER",
        "bio": "Streetwear clothing brand. Lagos.",
        "shop": "MADEBYLUTHER",
        "slug": "madebyluther",
        "state": "Lagos",
        "pickup": "MBL Studio, Yaba, Lagos",
        "delivery": ["Lagos", "Nationwide"],
        "products": [
            {
                "slug": "mbl-midnight-skully",
                "name": "MBL Midnight Skully",
                "category": "Accessories",
                "price": 15000,
                "stock": 30,
                "sold_count": 212,
                "popularity": 89,
                "description": "Black skull cap in soft brushed cotton with the Madebyluther script embroidered across the cuff.",
                "tags": ["skully", "cap", "mbl"],
                "image_url": f"{IMG}/mbl-midnight-skully.webp",
                "image_alt": "Black Madebyluther skull cap with embroidered script",
            },
            {
                "slug": "mbl-panthera-skully",
                "name": "MBL Panthera Skully",
                "category": "Accessories",
                "price": 15000,
                "stock": 12,
                "sold_count": 87,
                "popularity": 82,
                "description": "Leopard-print skull cap with the same embroidered script. Same cut as the Midnight, louder fabric.",
                "tags": ["skully", "leopard", "mbl"],
                "image_url": f"{IMG}/mbl-panthera-skully.webp",
                "image_alt": "Leopard-print Madebyluther skull cap",
            },
            {
                "slug": "mbl-world-cup-tee",
                "name": "MBL World Cup Tee",
                "category": "Fashion",
                "price": 30000,
                "stock": 16,
                "sold_count": 64,
                "popularity": 85,
                "description": "White tee with the World Cup map print on the front and 'Heroes Are Made' across the back. Heavyweight cotton.",
                "tags": ["tee", "mbl", "worldcup"],
                "image_url": f"{IMG}/mbl-world-cup-tee.webp",
                "image_alt": "White Madebyluther World Cup tee, front and back",
            },
        ],
    },
    {
        "username": "elexandco",
        "display_name": "Elex & Co",
        "bio": "Elegance. Luxury. Expression. Handcrafted jewellery.",
        "shop": "Elex & Co",
        "slug": "elex-and-co",
        "state": "Lagos",
        "pickup": "Elex & Co, Victoria Island, Lagos",
        "delivery": ["Lagos", "Nationwide"],
        "products": [
            {
                "slug": "elex-cipher-bracelet",
                "name": "The Cipher Bracelet",
                "category": "Accessories",
                "price": 25000,
                "stock": 11,
                "sold_count": 39,
                "popularity": 80,
                "description": "Silver-tone chain bracelet with black onyx beads and textured metal spacers. Lobster clasp, adjustable length.",
                "tags": ["bracelet", "jewellery", "elex"],
                "image_url": f"{IMG}/elex-cipher-bracelet.jpg",
                "image_alt": "Silver chain bracelet with black onyx beads",
            },
            {
                "slug": "elex-monolith-bracelet",
                "name": "The Monolith Double Strand Bracelet",
                "category": "Accessories",
                "price": 25000,
                "stock": 8,
                "sold_count": 27,
                "popularity": 76,
                "description": "Double-strand bracelet in brushed silver tone. Sits heavy on the wrist without catching on sleeves.",
                "tags": ["bracelet", "jewellery", "elex"],
                "image_url": f"{IMG}/elex-monolith-bracelet.jpg",
                "image_alt": "Double-strand silver bracelet",
            },
            {
                "slug": "elex-matturi-silver-wave",
                "name": "Matturi Silver Wave",
                "category": "Accessories",
                "price": 55000,
                "stock": 5,
                "sold_count": 18,
                "popularity": 79,
                "description": "Hand-finished wave-form silver piece from the Matturi line. Each one is polished by hand, so no two sit exactly alike.",
                "tags": ["jewellery", "silver", "elex"],
                "image_url": f"{IMG}/elex-matturi-silver-wave.png",
                "image_alt": "Polished silver wave jewellery piece",
            },
        ],
    },
    {
        "username": "spworm",
        "display_name": "SpaceWorm",
        "bio": "SpaceWorm — @spworm.xyz",
        "shop": "SpaceWorm",
        "slug": "spaceworm",
        "state": "Lagos",
        "pickup": None,
        "delivery": ["Lagos"],
        # No listings on purpose: spworm.xyz no longer resolves, so there is no
        # product data to copy. The shop exists so the handle is taken and the
        # profile can be filled in the moment the brand sends its own photos.
        "products": [],
    },
    {
        "username": "thebest",
        "display_name": "CampusTech Store",
        "bio": "Campus essentials — tech, study gear and hot food, delivered.",
        "shop": "CampusTech Store",
        "slug": "campustech-store",
        "state": "Ogun",
        "pickup": "CampusTech, Faculty Road, Bells University",
        "delivery": ["Bells University", "Ota", "Lagos"],
        "products": [
            {
                "slug": "campus-essential-hoodie",
                "name": "Campus Essential Hoodie",
                "category": "Fashion",
                "price": 18500,
                "was_price": 24000,
                "stock": 12,
                "sold_count": 480,
                "popularity": 96,
                "description": "Heavyweight fleece hoodie cut for campus weather. Kangaroo pocket, ribbed cuffs, no logo on the front.",
                "tags": ["hoodie", "campuswear", "unisex"],
                "image_url": f"{U}1556821840-3a63f95609a7?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Folded grey hoodie on a plain background",
            },
            {
                "slug": "airflux-midnight",
                "name": "AirFlux Midnight",
                "category": "Fashion",
                "price": 42000,
                "stock": 4,
                "sold_count": 320,
                "popularity": 94,
                "description": "Low-profile trainer with a cushioned midsole. Runs true to size; half a size up if you wear thick socks.",
                "tags": ["sneakers", "shoes"],
                "image_url": f"{U}1542291026-7eec264c27ff?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Red and white sneaker photographed from the side",
            },
            {
                "slug": "wireless-earbuds-pro",
                "name": "Wireless Earbuds Pro",
                "category": "Electronics",
                "price": 22500,
                "was_price": 28000,
                "stock": 9,
                "sold_count": 412,
                "popularity": 90,
                "description": "Active-noise earbuds with a pocketable charging case. Six hours a charge, twenty-four with the case.",
                "tags": ["earbuds", "audio", "anc"],
                "image_url": f"{U}1590658268037-6bf12165a8df?q=80&w=600&auto=format&fit=crop",
                "image_alt": "White wireless earbuds beside their charging case",
            },
            {
                "slug": "power-bank-20000",
                "name": "Power Bank 20,000mAh",
                "category": "Electronics",
                "price": 14500,
                "was_price": 19000,
                "stock": 31,
                "sold_count": 655,
                "popularity": 92,
                "description": "Fast-charge power bank with two USB-C ports. Charges a phone four times over, or a laptop once.",
                "tags": ["power bank", "charger", "usb-c"],
                "image_url": f"{U}1609091839311-d5365f9ff1c5?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Black power bank with a charging cable",
            },
            {
                "slug": "everyday-wristwatch",
                "name": "Everyday Wristwatch",
                "category": "Accessories",
                "price": 12500,
                "was_price": 18000,
                "stock": 7,
                "sold_count": 210,
                "popularity": 85,
                "description": "Minimal steel watch with a soft leather strap. Water-resistant enough for rain and a wash, not for swimming.",
                "tags": ["watch", "minimal", "leather"],
                "image_url": f"{U}1524805444758-089113d48a6d?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Wristwatch with a metal case and dark strap",
            },
            {
                "slug": "led-study-lamp",
                "name": "LED Study Lamp",
                "category": "Electronics",
                "price": 7400,
                "stock": 0,
                "sold_count": 275,
                "popularity": 78,
                "description": "Clamp-on desk lamp with three colour temperatures. Clips to a bunk frame or a shelf edge, no base needed.",
                "tags": ["lamp", "desk", "study"],
                "image_url": f"{U}1507473885765-e6ed057f782c?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Grey desk lamp on a work surface",
            },
            {
                # Slug kept from the first seed so any post that tagged it still
                # resolves. The NAME and the PHOTO are what changed: the old pair
                # was "Hardcover Notebook Set" over a photo of a laptop.
                "slug": "hardcover-notebook-set",
                "name": "A5 Spiral Notebook Set (3-Pack)",
                "category": "Stationery",
                "price": 4200,
                "stock": 3,
                "sold_count": 145,
                "popularity": 70,
                "description": "Three A5 spiral notebooks — dotted, ruled and blank. Lies flat at the fold, which is the whole reason to buy spiral over glued.",
                "tags": ["notebook", "a5", "stationery"],
                "image_url": f"{U}1531346878377-a5be20888e57?q=80&w=600&auto=format&fit=crop",
                "image_alt": "Spiral notebooks open on a desk beside a keyboard",
            },
            {
                "slug": "jollof-rice-combo",
                "name": "Jollof Rice & Grilled Chicken",
                "category": "Food",
                "price": 3200,
                "was_price": 4000,
                "stock": 25,
                "sold_count": 1840,
                "popularity": 91,
                "description": "Smoky party jollof with a grilled chicken quarter, fried plantain and coleslaw. Cooked in batches from 11am, out the door in 25 minutes.",
                "tags": ["jollof", "lunch", "rice"],
                "image_url": "/static/images/products/jollof-rice-combo.jpg",
                "image_alt": "Plate of jollof rice with grilled chicken and plantain",
            },
        ],
    },
]


def _build_org(db, user: User, spec: dict, sme_id) -> Organization:
    org = Organization(
        official_name=spec["shop"],
        short_name=spec["shop"],
        slug=spec["slug"],
        country="Nigeria",
        state=spec["state"],
        status=OrganizationStatus.ACTIVE.value,
        organization_type_id=sme_id,
        owner_user_id=user.id,
        pickup_address=spec["pickup"],
    )
    db.add(org)
    return org


async def main() -> None:
    if not os.environ["DATABASE_URL"].startswith("sqlite"):
        sys.exit("Refusing to seed a non-SQLite database.")

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        sme_id = (
            await db.execute(
                select(OrganizationType.id).where(OrganizationType.slug == "sme").limit(1)
            )
        ).scalar_one_or_none()

        for spec in BRANDS:
            user = (
                await db.execute(
                    select(User).where(
                        User.username_normalized == spec["username"].lower()
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    email=f"{spec['username'].replace('.', '')}@cartflow.demo",
                    password_hash=hash_password(DEFAULT_PASSWORD),
                    username=spec["username"],
                    username_normalized=spec["username"].lower(),
                    display_name=spec["display_name"],
                    bio=spec["bio"],
                    account_type=AccountType.BUSINESS,
                    account_status=AccountStatus.ACTIVE,
                    is_seller=True,
                )
                db.add(user)
                await db.flush()
                print(f"account @{user.username} created")

            org = (
                await db.execute(
                    select(Organization).where(Organization.owner_user_id == user.id)
                )
            ).scalar_one_or_none()
            if org is None:
                # A pre-existing curated org (CampusTech) has no owner, so adopt
                # the one this slug names rather than leaving the shop ownerless.
                org = (
                    await db.execute(
                        select(Organization).where(Organization.slug == spec["slug"])
                    )
                ).scalar_one_or_none()
            if org is None:
                org = _build_org(db, user, spec, sme_id)
                await db.flush()
                print(f"shop {org.slug} created for @{user.username}")
            elif org.owner_user_id is None:
                org.owner_user_id = user.id
                print(f"shop {org.slug} adopted by @{user.username}")

            org.pickup_address = spec["pickup"]
            org.short_name = spec["shop"]

            for item in spec["products"]:
                existing = (
                    await db.execute(select(Product).where(Product.slug == item["slug"]))
                ).scalar_one_or_none()
                payload = {
                    **item,
                    "organization_id": org.id,
                    "delivery_areas": spec["delivery"],
                    "pickup_address": spec["pickup"],
                    "status": ProductStatus.ACTIVE.value,
                }
                if existing is None:
                    db.add(Product(**payload))
                else:
                    # Upsert on purpose: this is how a wrong photo gets fixed.
                    for field, value in payload.items():
                        setattr(existing, field, value)

        await db.commit()

        total = (await db.execute(select(Product))).scalars().all()
        rows = len(total)
        shops = len(BRANDS)
        print(f"seed_products: {rows} listings across {shops} shops.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
