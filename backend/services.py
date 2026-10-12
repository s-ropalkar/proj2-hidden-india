import re
from datetime import datetime, timezone

from db import col

# Map quiz crafts/regions to searchable tags
CRAFT_ALIASES = {
    "warli": ["Warli Art", "Warli paintings", "Mural Arts"],
    "pottery": ["Pottery", "Ceramics", "Blue Pottery", "Ceramic Arts"],
    "textile": ["Textiles", "Indian Textiles", "Weaving"],
    "wood": ["Wood Carving", "Carpentry"],
    "madhubani": ["Madhubani Art", "Folk Art"],
}

REGION_ALIASES = {
    "north india": ["Rajasthan", "Uttar Pradesh", "Delhi", "Punjab"],
    "south india": ["Karnataka", "Kerala", "Tamil Nadu", "Andhra Pradesh"],
    "west india": ["Maharashtra", "Gujarat", "Goa"],
    "east india": ["West Bengal", "Bihar", "Odisha", "Jharkhand"],
    "north east india": ["Assam", "Manipur", "Meghalaya", "Nagaland", "Tripura", "Arunachal Pradesh", "Mizoram", "Sikkim"],
    "central india": ["Madhya Pradesh", "Chhattisgarh"],
    "maharashtra": ["Maharashtra"],
    "rajasthan": ["Rajasthan"],
}


def process_cultural_dna(quiz: dict) -> dict:
    """Convert quiz answers into stored interests and focus regions."""
    interests = set(quiz.get("interests", []))
    interests.update(quiz.get("crafts", []))

    if quiz.get("workshopInterest", "").lower().startswith("yes"):
        interests.add("Workshops")

    regions = []
    for r in quiz.get("regions", []):
        if r.lower() == "no preference":
            continue
        key = r.lower()
        regions.extend(REGION_ALIASES.get(key, [r.replace(" India", "")]))

    geographic_focus = ", ".join(regions[:2]) if regions else "Pan India"

    return {
        "interests": sorted(interests),
        "geographic_focus": geographic_focus,
        "preferred_states": list(dict.fromkeys(regions)),
        "budget": quiz.get("budget", ""),
        "visit_reason": quiz.get("visitReason", ""),
        "quiz_answers": quiz,
        "quiz_completed_at": datetime.now(timezone.utc),
    }


def hidden_gem_score(doc: dict) -> float:
    """
    Hidden Gem Score = low popularity + high rating + regional uniqueness.
    Returns 0–10 scale.
    """
    popularity = doc.get("popularity", 50)  # 0=famous, 100=hidden
    rating = doc.get("rating", 4.0)
    uniqueness = doc.get("regional_uniqueness", 5.0)

    low_pop = popularity / 10.0  # higher when less popular
    rating_score = rating * 2.0  # 0-10
    unique_score = uniqueness

    score = low_pop * 0.35 + rating_score * 0.45 + unique_score * 0.20
    return round(min(10.0, max(0.0, score)), 1)


def _interest_keywords(user: dict) -> set[str]:
    keywords = set()
    for item in user.get("interests", []):
        keywords.add(item.lower())
    for craft_list in CRAFT_ALIASES.values():
        for c in craft_list:
            if any(k in c.lower() for k in keywords):
                keywords.add(c.lower())
    for state in user.get("preferred_states", []):
        keywords.add(state.lower())
    return keywords


def recommend_for_user(user_id: str, limit: int = 6) -> dict:
    user = col("users").find_one({"_id": user_id}) or {}
    keywords = _interest_keywords(user)
    preferred_states = [s.lower() for s in user.get("preferred_states", []) if s]

    saved_artisan_ids = [
        s["item_id"]
        for s in col("saved_items").find({"user_id": user_id, "item_type": "artisan"})
    ]
    saved_product_ids = [
        s["item_id"]
        for s in col("saved_items").find({"user_id": user_id, "item_type": "product"})
    ]

    artisan_query: dict = {"status": "active"}
    product_query: dict = {"status": "In Stock"}
    workshop_query: dict = {"status": "open"}
    region_query: dict = {}

    or_clauses_artisan = []
    or_clauses_product = []
    or_clauses_workshop = []

    if keywords:
        for k in keywords:
            pat = {"$regex": re.escape(k), "$options": "i"}
            or_clauses_artisan.append({"category": pat})
            or_clauses_product.append({"category": pat})
            or_clauses_product.append({"craft": pat})
            or_clauses_workshop.append({"category": pat})
            or_clauses_workshop.append({"craft": pat})
            region_query.setdefault("$or", []).append({"name": pat})
            region_query.setdefault("$or", []).append({"state": pat})

    if preferred_states:
        for s in preferred_states:
            pat = {"$regex": re.escape(s), "$options": "i"}
            or_clauses_artisan.append({"state": pat})
            or_clauses_product.append({"state": pat})
            or_clauses_workshop.append({"state": pat})

    if or_clauses_artisan:
        artisan_query["$or"] = or_clauses_artisan
    if or_clauses_product:
        product_query["$or"] = or_clauses_product
    if or_clauses_workshop:
        workshop_query["$or"] = or_clauses_workshop

    def _fetch(collection: str, query: dict, fallback: dict) -> list:
        items = list(col(collection).find(query).limit(limit * 4))
        if not items:
            items = list(col(collection).find(fallback).limit(limit * 4))
        return items

    artisans = _fetch("artisans", artisan_query, {"status": "active"})
    products = _fetch("products", product_query, {"status": "In Stock"})
    workshops = _fetch("workshops", workshop_query, {"status": "open"})
    regions = list(col("regions").find(region_query or {}).limit(limit))
    if not regions:
        regions = list(col("regions").find().limit(limit))

    def rank(items, id_field="_id"):
        scored = []
        for item in items:
            score = hidden_gem_score(item)
            item_id = str(item.get(id_field, item.get("_id")))
            if item_id in saved_artisan_ids or item_id in saved_product_ids:
                score += 2
            st = (item.get("state") or "").lower()
            if preferred_states and any(ps in st for ps in preferred_states):
                score += 1.5
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [i for _, i in scored[:limit]]

    return {
        "artisans": rank(artisans),
        "products": rank(products),
        "workshops": rank(workshops),
        "regions": regions[:limit],
    }


def geo_near(query: dict, lat: float, lng: float, km: float, limit: int = 20) -> list:
    return list(
        col(query["_collection"]).find(
            {
                **query.get("filter", {}),
                "location": {
                    "$near": {
                        "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                        "$maxDistance": km * 1000,
                    }
                },
            }
        ).limit(limit)
    )


def point(lng: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lng, lat]}
