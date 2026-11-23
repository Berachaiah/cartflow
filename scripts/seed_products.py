"""
Dev-only: give the preview shop something to sell.

The catalogue used to render a curated list, so the Shop was never empty. Now it
reads the `products` table, which means a freshly synced `dev_preview.db` renders
an honest empty grid — correct, and useless for looking at the layout.

This seeds a handful of listings for one demo business so `/marketplace` and
`/product/{slug}` can be exercised in a browser. It is a SEED, not a fallback:
if the table already has rows it does nothing, and nothing in the app reads it.

The slugs match the ones `home.html`'s demo feed tags, so Home's product chips,
its photo badge and its Flash Deals panel have something to point at. That is a
property of this fixture, not something the templates may rely on — they cope
with a missing row by dropping the tag.

    DATABASE_URL=sqlite+aiosqlite:///./dev_preview.db \
        ./.venv/Scripts/python.exe scripts/seed_products.py

Run `scripts/dev_preview_sync.py` first — it creates the table.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.database.session import engine  # noqa: E402
from app.models.organization import Organization, OrganizationType  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.user import User  # noqa: E402

SAMPLE: list[dict] = [
    {
        "slug": "campus-essential-hoodie",
        "name": "Campus Essential Hoodie",
        "category": "Fashion",
        "price": 18500,
        "was_price": 24000,
        "stock": 12,
        "sold_count": 480,
        "popularity": 96,
        "description": "Heavyweight fleece hoodie cut for campus weather.",
        "tags": ["hoodie", "campuswear", "unisex"],
        "delivery_areas": ["Bells University", "Ota", "Lagos"],
        "pickup_address": "Main Gate, Bells University",
        "image_url": "https://images.unsplash.com/photo-1556821840-3a63f95609a7?q=80&w=600&auto=format&fit=crop",
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
        "description": "Low-profile trainer with a cushioned midsole.",
        "tags": ["sneakers", "shoes"],
        "delivery_areas": ["Covenant University", "Lagos", "Nationwide"],
        "pickup_address": "Shop 14, Covenant Plaza",
        "image_url": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Dark sneaker photographed from the side",
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
        "description": "Active-noise earbuds with a pocketable charging case.",
        "tags": ["earbuds", "audio", "anc"],
        "delivery_areas": ["Bells University", "Lagos", "Nationwide"],
        "pickup_address": "CampusTech, Faculty Road",
        "image_url": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?q=80&w=600&auto=format&fit=crop",
        "image_alt": "White wireless earbuds beside their case",
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
        "description": "Fast-charge power bank with two USB-C ports.",
        "tags": ["power bank", "charger", "usb-c"],
        "delivery_areas": ["Bells University", "Ota", "Lagos"],
        "pickup_address": "CampusTech, Faculty Road",
        "image_url": "https://images.unsplash.com/photo-1609091839311-d5365f9ff1c5?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Black power bank with a charging cable",
    },
    {
        "slug": "jollof-rice-combo",
        "name": "Jollof Rice Combo",
        "category": "Food",
        "price": 3200,
        "was_price": 4000,
        "stock": 25,
        "sold_count": 1840,
        "popularity": 91,
        "description": "Smoky party jollof with grilled chicken and plantain.",
        "tags": ["jollof", "lunch"],
        "delivery_areas": ["Bells University", "Ota"],
        "pickup_address": "FoodHub, Student Centre",
        "image_url": "https://images.unsplash.com/photo-1604329760661-e71dc83f8f26?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Plate of jollof rice with chicken",
    },
    {
        "slug": "everyday-wristwatch",
        "name": "Everyday Wristwatch",
        "category": "Fashion",
        "price": 12500,
        "was_price": 18000,
        "stock": 7,
        "sold_count": 210,
        "popularity": 85,
        "description": "Minimal steel watch with a soft leather strap.",
        "tags": ["watch", "minimal", "leather"],
        "delivery_areas": ["Bells University", "Ota", "Lagos"],
        "pickup_address": "Shop 14, Covenant Plaza",
        "image_url": "https://images.unsplash.com/photo-1524805444758-089113d48a6d?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Silver wristwatch with a brown leather strap",
    },
    {
        "slug": "led-study-lamp",
        "name": "LED Study Lamp",
        "category": "Electronics",
        "price": 7400,
        "stock": 0,
        "sold_count": 275,
        "popularity": 78,
        "description": "Clamp-on desk lamp with three colour temperatures.",
        "tags": ["lamp", "desk", "study"],
        "delivery_areas": ["Bells University", "Lagos"],
        "pickup_address": "CampusTech, Faculty Road",
        "image_url": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Lit desk lamp beside an open notebook",
    },
    {
        "slug": "hardcover-notebook-set",
        "name": "Hardcover Notebook Set",
        "category": "Stationery",
        "price": 4200,
        "stock": 3,
        "sold_count": 145,
        "popularity": 70,
        "description": "Three A5 hardcovers — dotted, ruled and blank.",
        "tags": ["notebook", "a5", "dotted"],
        "delivery_areas": ["Bells University", "Ota"],
        "pickup_address": "Inkwell, Ota Market",
        "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?q=80&w=600&auto=format&fit=crop",
        "image_alt": "Notebooks stacked on a study desk",
    },
]


async def main() -> None:
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        existing = (await db.execute(select(func.count()).select_from(Product))).scalar_one()
        if existing:
            print(f"seed_products: {existing} product(s) already present, nothing to do.")
            return

        org = (
            await db.execute(
                select(Organization)
                .where(Organization.owner_user_id.is_not(None))
                .order_by(Organization.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        if org is None:
            owner = (await db.execute(select(User).limit(1))).scalars().first()
            sme = (
                await db.execute(select(OrganizationType).where(OrganizationType.slug == "sme").limit(1))
            ).scalars().first()
            org = Organization(
                official_name="CampusTech Store",
                short_name="CampusTech Store",
                slug="campustech-store",
                country="Nigeria",
                state="Ogun",
                status="active",
                organization_type_id=sme.id if sme else None,
                owner_user_id=owner.id if owner else None,
            )
            db.add(org)
            await db.flush()
            print(f"seed_products: created demo business {org.slug!r}.")

        for item in SAMPLE:
            db.add(Product(organization_id=org.id, **item))

        await db.commit()
        print(f"seed_products: added {len(SAMPLE)} listings to {org.short_name}.")


if __name__ == "__main__":
    asyncio.run(main())
