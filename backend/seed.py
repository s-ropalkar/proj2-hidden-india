"""Seed the MySQL-backed catalog with data from google-images folders + demo accounts."""

import re
import sys
from datetime import datetime, timezone

from config import Config
from db import col, init_db
from auth import hash_password
from services import point
from india_data import IMAGE_BY_CATEGORY, pick_artisan_avatar
from google_images_catalog import scan_all, catalog_summary
from artisan_images_catalog import scan_portrait_artisans, portrait_summary

CATALOG_COLLECTIONS = ("regions", "artisans", "products", "workshops", "artisan_applications")


def _email_for(name: str) -> str:
    safe = name.lower().replace(" ", ".").replace("'", "").replace("·", "").replace("—", "")
    safe = re.sub(r"[^a-z0-9.@]+", "", safe)
    return f"{safe}@hiddenindia.in"


def clear_catalog():
    for name in CATALOG_COLLECTIONS:
        col(name).delete_many({})


def seed_users(now):
    if col("users").count_documents({}) > 0:
        return
    col("users").insert_many(
        [
            {
                "name": Config.ADMIN_NAME,
                "email": Config.ADMIN_EMAIL,
                "password": hash_password(Config.ADMIN_PASSWORD),
                "role": "admin",
                "status": "active",
                "interests": [],
                "geographic_focus": "Pan India",
                "avatar": "",
                "created_at": now,
            },
            {
                "name": "Aryan Deshpande",
                "email": "aryan@explorer.in",
                "password": hash_password("Explorer@123"),
                "role": "user",
                "status": "active",
                "interests": ["Warli Art", "Textile Arts", "Ceramics"],
                "geographic_focus": "Maharashtra & Western Ghats",
                "preferred_states": ["Maharashtra"],
                "avatar": pick_artisan_avatar("Aryan Deshpande"),
                "quiz_answers": {
                    "visitReason": "Cultural immersion",
                    "interests": ["Traditional Crafts"],
                    "crafts": ["Warli paintings", "Pottery"],
                    "regions": ["West India"],
                    "workshopInterest": "Yes, definitely",
                    "budget": "₹2,000 - ₹5,000",
                },
                "created_at": now,
            },
        ]
    )


def seed_india_catalog(now):
    """Seed regions/products/workshops from google-images; artisans only from google-images/artisans portraits."""
    catalogs = scan_all()
    if not catalogs:
        raise RuntimeError("No google-images catalog found. Check final_hidden_india/google-images/google-images")

    portraits = scan_portrait_artisans()
    if not portraits:
        raise RuntimeError(
            "No artisan portrait images found. Add folders under final_hidden_india/google-images/artisans/"
        )

    month_labels = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    month_idx = now.month - 1

    for state, catalog in catalogs.items():
        from india_data import STATE_COORDS

        if state not in portraits:
            continue

        state_portraits = portraits[state]
        lng, lat = STATE_COORDS[state]
        zone = catalog.zone

        col("regions").insert_one(
            {
                "name": state,
                "state": state,
                "zone": zone,
                "highlight_craft": catalog.highlight,
                "culture_summary": f"Discover authentic {catalog.highlight} heritage and hidden artisan communities across {state}.",
                "image": catalog.products[0].image if catalog.products else IMAGE_BY_CATEGORY.get("Decor"),
                "location": point(lng, lat),
                "culture": {
                    "folkTraditions": [catalog.highlight],
                    "heritageSites": [f"{state} Heritage Quarter"],
                    "festivals": ["Regional Craft Mela"],
                },
                "cuisine": [f"{state} traditional cuisine"],
                "regional_uniqueness": 8.0,
            }
        )

        artisan_ids: list[str] = []
        for portrait in state_portraits:
            artisan_ids.append(
                col("artisans").insert_one(
                    {
                        "user_id": None,
                        "name": portrait.name,
                        "email": _email_for(portrait.name),
                        "category": portrait.category,
                        "approved_crafts": [catalog.highlight, portrait.category],
                        "crafts": [catalog.highlight],
                        "region": f"{state}, India",
                        "state": state,
                        "bio": portrait.bio,
                        "avatar": portrait.avatar,
                        "highlight_image": portrait.avatar,
                        "tag": portrait.tag,
                        "status": "active",
                        "rating": 4.5,
                        "popularity": 55,
                        "regional_uniqueness": 8.5,
                        "profile_views": 0,
                        "save_count": 0,
                        "location": point(lng, lat),
                        "zone": zone,
                        "created_at": now,
                    }
                ).inserted_id
            )

        primary_id = artisan_ids[0] if artisan_ids else None

        for i, product in enumerate(catalog.products):
            artisan_id = artisan_ids[i % len(artisan_ids)]
            assigned = state_portraits[i % len(state_portraits)]
            price = max(product.base_price, 500)
            col("products").insert_one(
                {
                    "artisan_id": artisan_id,
                    "name": product.name,
                    "description": f"Authentic {product.name} handcrafted by {assigned.name} in {state}.",
                    "material": product.craft,
                    "price_num": price,
                    "price_display": f"₹{price:,}",
                    "category": product.category,
                    "craft": product.craft,
                    "state": state,
                    "zone": zone,
                    "image": product.image,
                    "status": "In Stock",
                    "popularity": 50,
                    "rating": 4.4,
                    "regional_uniqueness": 8.0,
                    "save_count": 0,
                    "view_count": 0,
                    "order_count": 0,
                    "created_at": now,
                }
            )

        for i, workshop in enumerate(catalog.workshops):
            ws_month = month_labels[(month_idx + i) % 12]
            is_online = i % 2 == 1
            instructor = state_portraits[0].name
            col("workshops").insert_one(
                {
                    "artisan_id": primary_id,
                    "title": workshop.title,
                    "instructor": instructor,
                    "instructor_avatar": state_portraits[0].avatar,
                    "date": f"{ws_month} {15 + i * 3}",
                    "time": "10:00 AM - 1:00 PM" if not is_online else "2:30 PM - 5:30 PM",
                    "price": 2800 + i * 1200,
                    "price_display": f"₹{2800 + i * 1200:,}",
                    "category": workshop.category,
                    "thumbnail": workshop.image,
                    "venue": "" if is_online else f"{state} Heritage Arts Center",
                    "mode": "online" if is_online else "offline",
                    "seats": 20,
                    "state": state,
                    "zone": zone,
                    "status": "open",
                    "location": point(lng, lat),
                    "registration_count": 0,
                    "popularity": 45,
                    "rating": 4.6,
                    "regional_uniqueness": 8.5,
                    "created_at": now,
                }
            )

def seed_demo_activity(now):
    user = col("users").find_one({"email": "aryan@explorer.in"})
    if not user:
        return

    maharashtra_ws = col("workshops").find_one({"state": "Maharashtra"})
    rajasthan_ws = col("workshops").find_one({"state": "Rajasthan", "mode": "offline"})
    if not maharashtra_ws or not rajasthan_ws:
        return

    col("workshop_registrations").delete_many({"user_id": user["_id"]})
    col("workshop_registrations").insert_one(
        {
            "user_id": user["_id"],
            "workshop_id": maharashtra_ws["_id"],
            "session_id": "session-1",
            "status": "Registration Submitted",
            "created_at": now,
        }
    )
    col("workshop_registrations").insert_one(
        {
            "user_id": user["_id"],
            "workshop_id": rajasthan_ws["_id"],
            "session_id": "session-1",
            "status": "Attended",
            "attended": True,
            "created_at": now,
        }
    )

    product = col("products").find_one({"state": "Maharashtra"})
    if product and col("orders").count_documents({"user_id": user["_id"]}) == 0:
        col("orders").insert_one(
            {
                "user_id": user["_id"],
                "product_id": product["_id"],
                "artisan_id": product.get("artisan_id"),
                "quantity": 1,
                "total": product.get("price_num", 0),
                "status": "Placed",
                "buy_now": True,
                "created_at": now,
            }
        )


def seed(force=False):
    init_db(Config.MYSQL_URI)
    now = datetime.now(timezone.utc)
    region_count = col("regions").count_documents({})
    expected_states = len(scan_all())

    if force or region_count < expected_states:
        if region_count > 0:
            print(f"Refreshing catalog from google-images ({expected_states} states)...")
            clear_catalog()
        else:
            print(f"Seeding catalog from google-images ({expected_states} states)...")
        seed_india_catalog(now)
        summary = catalog_summary(scan_all())
        artisans = portrait_summary(scan_portrait_artisans())
        print(f"  -> {summary['states']} regions (states with portrait folders)")
        print(f"  -> {artisans['artisans']} artisans (from google-images/artisans portraits only)")
        print(f"  -> {summary['products']} products (from your image folders)")
        print(f"  -> {summary['workshops']} workshops (only folders with images)")

    seed_users(now)
    seed_demo_activity(now)

    print("Seed complete!")
    print(f"  Admin: {Config.ADMIN_EMAIL} / {Config.ADMIN_PASSWORD}")
    print("  Demo user: aryan@explorer.in / Explorer@123")


if __name__ == "__main__":
    force = "--force" in sys.argv or "-f" in sys.argv
    seed(force=force)
