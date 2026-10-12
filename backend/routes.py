import json
import os
import re
import uuid
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    login_required,
    role_required,
    serialize_user,
    verify_password,
)
from config import Config
from db import col
from ids import as_id
from region_crafts import (
    all_catalog_crafts,
    artisan_craft_allowed,
    crafts_for_state,
    infer_product_category,
    list_states,
    normalize_state,
    state_coordinates,
    validate_application_crafts,
)
from services import hidden_gem_score, point, process_cultural_dna, recommend_for_user

api = Blueprint("api", __name__, url_prefix="/api")


def oid(value: str):
    return as_id(value)


def as_datetime(value):
    """Normalize MySQL-JSON timestamps (str) or datetime objects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def dt_isoformat(value) -> str:
    dt = as_datetime(value) or datetime.now(timezone.utc)
    return dt.isoformat()


def dt_strftime(value, fmt: str = "%b %d, %Y") -> str:
    dt = as_datetime(value) or datetime.now(timezone.utc)
    return dt.strftime(fmt)


@api.get("/catalog/states")
def catalog_states():
    return jsonify(
        {
            "states": list_states(),
            "craftsByState": {s: crafts_for_state(s) for s in list_states()},
        }
    )


@api.post("/catalog/validate-crafts")
def catalog_validate_crafts():
    data = request.get_json(silent=True) or {}
    state = (data.get("state") or "").strip()
    crafts = data.get("crafts") or []
    if isinstance(crafts, str):
        crafts = [c.strip() for c in crafts.split(",") if c.strip()]
    return jsonify(validate_application_crafts(state, crafts))


@api.get("/catalog/crafts")
def catalog_crafts():
    return jsonify({"crafts": all_catalog_crafts()})


def serialize_doc(doc: dict, id_key: str = "id") -> dict:
    if not doc:
        return {}
    out: dict = {}
    for k, v in doc.items():
        if k == "_id":
            continue
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k == "location" and isinstance(v, dict):
            coords = v.get("coordinates", [0, 0])
            out["lng"] = coords[0]
            out["lat"] = coords[1]
        else:
            out[k] = v
    out[id_key] = str(doc["_id"])
    if doc.get("artisan_id"):
        out["artisanId"] = str(doc["artisan_id"])
    if doc.get("user_id"):
        out["userId"] = str(doc["user_id"])
    if "gem_score" not in out and any(k in doc for k in ("popularity", "rating")):
        out["gemScore"] = hidden_gem_score(doc)
    return out


def save_upload(file_storage, subfolder: str) -> str:
    if not file_storage or not file_storage.filename:
        return ""
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
        raise ValueError("Unsupported file type")
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subfolder)
    os.makedirs(folder, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(folder, filename)
    file_storage.save(path)
    return f"/uploads/{subfolder}/{filename}"


def push_notification(user_id, ntype: str, title: str, message: str, meta: dict | None = None):
    uid = as_id(user_id)
    col("notifications").insert_one(
        {
            "user_id": uid,
            "type": ntype,
            "title": title,
            "message": message,
            "meta": meta or {},
            "read": False,
            "created_at": datetime.now(timezone.utc),
        }
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

@api.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or data.get("fullName") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or len(password) < 6:
        return jsonify({"error": "Name, valid email, and password (6+ chars) required"}), 400
    if not re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", email):
        return jsonify({"error": "Invalid email format"}), 400
    if col("users").find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409

    user = {
        "name": name,
        "email": email,
        "password": hash_password(password),
        "role": "user",
        "status": "active",
        "interests": [],
        "geographic_focus": "",
        "preferred_states": [],
        "avatar": "",
        "created_at": datetime.now(timezone.utc),
    }
    try:
        result = col("users").insert_one(user)
    except Exception as exc:
        current_app.logger.exception("User registration failed")
        msg = "Registration failed. Check that MySQL is running."
        if os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True"):
            msg = f"{msg} ({type(exc).__name__})"
        return jsonify({"error": msg}), 500
    user["_id"] = result.inserted_id
    token = create_access_token(str(result.inserted_id), "user")
    return jsonify({"token": token, "user": serialize_user(user)}), 201


@api.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = col("users").find_one({"email": email})
    if not user or not verify_password(password, user["password"]):
        return jsonify({"error": "Invalid email or password"}), 401
    if user.get("status") == "blocked":
        return jsonify({"error": "Account blocked"}), 403
    token = create_access_token(str(user["_id"]), user.get("role", "user"))
    return jsonify({"token": token, "user": serialize_user(user)})


@api.get("/auth/me")
@login_required
def auth_me(user):
    return jsonify({"user": serialize_user(user, include_private=True)})


# ── User profile & quiz ───────────────────────────────────────────────────────

@api.get("/users/me")
@login_required
def get_me(user):
    return jsonify(serialize_user(user, include_private=True))


@api.patch("/users/me")
@login_required
def update_me(user):
    data = request.get_json(silent=True) or {}
    updates = {}
    if "name" in data:
        updates["name"] = data["name"].strip()
    if "geographicFocus" in data:
        updates["geographic_focus"] = data["geographicFocus"]
    if "interests" in data and isinstance(data["interests"], list):
        updates["interests"] = data["interests"]
    if "avatar" in data:
        updates["avatar"] = data["avatar"]
    if updates:
        col("users").update_one({"_id": user["_id"]}, {"$set": updates})
        user = col("users").find_one({"_id": user["_id"]})
    return jsonify(serialize_user(user))


@api.post("/users/me/quiz")
@login_required
def save_quiz(user):
    quiz = request.get_json(silent=True) or {}
    dna = process_cultural_dna(quiz)
    col("users").update_one({"_id": user["_id"]}, {"$set": dna})
    user = col("users").find_one({"_id": user["_id"]})
    return jsonify({"success": True, "profile": serialize_user(user), "interests": dna["interests"]})


@api.get("/users/me/recommendations")
@login_required
def recommendations(user):
    rec = recommend_for_user(user["_id"])
    return jsonify(
        {
            "artisans": [serialize_doc(a) for a in rec["artisans"]],
            "products": [serialize_doc(p) for p in rec["products"]],
            "workshops": [serialize_doc(w) for w in rec["workshops"]],
            "regions": [serialize_doc(r) for r in rec["regions"]],
        }
    )


# ── Saved items ───────────────────────────────────────────────────────────────

@api.get("/users/me/saved")
@login_required
def list_saved(user):
    items = list(col("saved_items").find({"user_id": user["_id"]}))
    result = []
    for item in items:
        doc = None
        if item["item_type"] == "product":
            doc = col("products").find_one({"_id": item["item_id"]})
        elif item["item_type"] == "artisan":
            doc = col("artisans").find_one({"_id": item["item_id"]})
        if doc:
            serialized = serialize_doc(doc)
            serialized["savedType"] = item["item_type"]
            result.append(serialized)
    return jsonify(result)


@api.post("/users/me/saved")
@login_required
def save_item(user):
    data = request.get_json(silent=True) or {}
    item_type = data.get("itemType") or data.get("type")
    item_id = data.get("itemId") or data.get("id")
    oid_val = oid(item_id)
    if item_type not in {"product", "artisan"} or not oid_val:
        return jsonify({"error": "itemType (product|artisan) and itemId required"}), 400
    col("saved_items").update_one(
        {"user_id": user["_id"], "item_type": item_type, "item_id": oid_val},
        {"$set": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    if item_type == "artisan":
        col("artisans").update_one({"_id": oid_val}, {"$inc": {"save_count": 1}})
    elif item_type == "product":
        col("products").update_one({"_id": oid_val}, {"$inc": {"save_count": 1}})
    return jsonify({"success": True}), 201


@api.delete("/users/me/saved/<item_type>/<item_id>")
@login_required
def unsave_item(user, item_type, item_id):
    oid_val = oid(item_id)
    if not oid_val:
        return jsonify({"error": "Invalid id"}), 400
    result = col("saved_items").delete_one(
        {"user_id": user["_id"], "item_type": item_type, "item_id": oid_val}
    )
    if result.deleted_count and item_type in {"product", "artisan"}:
        col(f"{item_type}s" if item_type == "product" else "artisans").update_one(
            {"_id": oid_val},
            {"$inc": {"save_count": -1}},
        )
    return jsonify({"success": True})


# ── Orders ────────────────────────────────────────────────────────────────────

@api.post("/orders")
@login_required
def place_order(user):
    data = request.get_json(silent=True) or {}
    product_id = oid(data.get("productId"))
    quantity = int(data.get("quantity", 1))
    buy_now = data.get("buyNow", True)
    if not product_id or quantity < 1:
        return jsonify({"error": "productId and quantity required"}), 400
    product = col("products").find_one({"_id": product_id})
    if not product or product.get("status") != "In Stock":
        return jsonify({"error": "Product unavailable"}), 404
    order = {
        "user_id": user["_id"],
        "product_id": product_id,
        "artisan_id": product.get("artisan_id"),
        "quantity": quantity,
        "total": product.get("price_num", 0) * quantity,
        "status": "Placed",
        "buy_now": buy_now,
        "created_at": datetime.now(timezone.utc),
    }
    result = col("orders").insert_one(order)
    col("products").update_one({"_id": product_id}, {"$inc": {"order_count": quantity}})
    artisan_id = product.get("artisan_id")
    if artisan_id:
        col("artisans").update_one({"_id": artisan_id}, {"$inc": {"sales_total": order["total"]}})
    push_notification(
        user["_id"],
        "order",
        "Order Placed",
        f'Your order for "{product.get("name")}" has been placed successfully.',
        {"orderId": str(result.inserted_id), "productId": str(product_id)},
    )
    if not buy_now:
        cart = [e for e in user.get("cart", []) if e["product_id"] != product_id]
        col("users").update_one({"_id": user["_id"]}, {"$set": {"cart": cart}})
    return jsonify({"orderId": str(result.inserted_id), "status": "Placed"}), 201


@api.get("/users/me/orders")
@login_required
def my_orders(user):
    orders = list(col("orders").find({"user_id": user["_id"]}).sort("created_at", -1))
    out = []
    for o in orders:
        product = col("products").find_one({"_id": o["product_id"]})
        out.append(
            {
                "id": str(o["_id"]),
                "status": o["status"],
                "quantity": o["quantity"],
                "total": o["total"],
                "product": serialize_doc(product) if product else None,
                "createdAt": dt_isoformat(o["created_at"]),
            }
        )
    return jsonify(out)


# ── Workshop bookings ─────────────────────────────────────────────────────────

@api.get("/users/me/workshops")
@login_required
def my_workshops(user):
    regs = list(col("workshop_registrations").find({"user_id": user["_id"]}).sort("created_at", -1))
    upcoming = []
    attended = []
    attended_statuses = {"Attended", "Completed", "attended", "completed"}
    for r in regs:
        ws = col("workshops").find_one({"_id": r["workshop_id"]})
        if not ws:
            continue
        mode = ws.get("mode", "offline")
        entry = {
            "id": str(r["_id"]),
            "registrationId": str(r["_id"]),
            "workshopId": str(ws["_id"]),
            "name": ws.get("title"),
            "host": ws.get("instructor"),
            "date": ws.get("date"),
            "time": ws.get("time"),
            "price": ws.get("price_display", ws.get("price")),
            "status": r.get("status", "Registration Submitted"),
            "mode": mode,
            "venue": ws.get("venue", "") if mode != "online" else "",
        }
        if r.get("attended") or r.get("status") in attended_statuses:
            attended.append(entry)
        else:
            upcoming.append(entry)
    return jsonify({"upcoming": upcoming, "attended": attended})


@api.get("/users/me/notifications")
@login_required
def my_notifications(user):
    notes = list(
        col("notifications")
        .find({"user_id": user["_id"]})
        .sort("created_at", -1)
        .limit(50)
    )
    unread = col("notifications").count_documents({"user_id": user["_id"], "read": False})
    return jsonify(
        {
            "unread": unread,
            "items": [
                {
                    "id": str(n["_id"]),
                    "type": n.get("type"),
                    "title": n.get("title"),
                    "message": n.get("message"),
                    "read": n.get("read", False),
                    "createdAt": dt_isoformat(n.get("created_at")),
                    "meta": n.get("meta") or {},
                }
                for n in notes
            ],
        }
    )


@api.patch("/users/me/notifications/read")
@login_required
def mark_notifications_read(user):
    col("notifications").update_many({"user_id": user["_id"], "read": False}, {"$set": {"read": True}})
    return jsonify({"success": True})


@api.post("/products/<product_id>/view")
@login_required
def track_product_view(user, product_id):
    p_oid = oid(product_id)
    if p_oid:
        col("products").update_one({"_id": p_oid}, {"$inc": {"view_count": 1}})
    return jsonify({"success": True})


# ── Workshops (public) ────────────────────────────────────────────────────────

@api.post("/workshops/<workshop_id>/register")
@login_required
def register_workshop(user, workshop_id):
    ws_oid = oid(workshop_id)
    if not ws_oid:
        return jsonify({"error": "Invalid workshop id"}), 400
    workshop = col("workshops").find_one({"_id": ws_oid})
    if not workshop:
        return jsonify({"error": "Workshop not found"}), 404
    seats_taken = col("workshop_registrations").count_documents({"workshop_id": ws_oid})
    if col("workshop_registrations").count_documents({"user_id": user["_id"], "workshop_id": ws_oid}):
        return jsonify({"error": "Already registered"}), 409
    if seats_taken >= workshop.get("seats", 20):
        return jsonify({"error": "Workshop full"}), 409
    data = request.get_json(silent=True) or {}
    reg = {
        "user_id": user["_id"],
        "workshop_id": ws_oid,
        "session_id": data.get("sessionId", "session-1"),
        "status": "Registration Submitted",
        "created_at": datetime.now(timezone.utc),
    }
    try:
        col("workshop_registrations").insert_one(reg)
    except Exception:
        return jsonify({"error": "Already registered"}), 409
    col("workshops").update_one({"_id": ws_oid}, {"$inc": {"registration_count": 1}})
    push_notification(
        user["_id"],
        "workshop",
        "Workshop Registration Successful",
        f'You are registered for "{workshop["title"]}" on {workshop.get("date", "TBD")}. Reminder will be sent before the session.',
        {"workshopId": str(ws_oid)},
    )
    return jsonify(
        {
            "name": workshop["title"],
            "host": workshop["instructor"],
            "date": workshop["date"],
            "time": workshop["time"],
            "price": workshop.get("price_display"),
            "status": "Registration Submitted",
        }
    ), 201


# ── Artisans (public) ─────────────────────────────────────────────────────────

@api.get("/artisans")
def list_artisans():
    q = request.args.get("q", "").strip()
    craft = request.args.get("craft", "").strip()
    state = request.args.get("state", "").strip()
    filt = {"status": "active"}
    if craft:
        filt["category"] = {"$regex": craft, "$options": "i"}
    if state:
        filt["state"] = {"$regex": state, "$options": "i"}
    if q:
        filt["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"category": {"$regex": q, "$options": "i"}},
            {"bio": {"$regex": q, "$options": "i"}},
        ]
    artisans = list(col("artisans").find(filt).limit(200))
    for a in artisans:
        a["gemScore"] = hidden_gem_score(a)
    return jsonify([serialize_doc(a) for a in artisans])


@api.get("/artisans/<artisan_id>")
def get_artisan(artisan_id):
    a = col("artisans").find_one({"_id": oid(artisan_id), "status": "active"})
    if not a:
        return jsonify({"error": "Artisan not found"}), 404
    col("artisans").update_one({"_id": a["_id"]}, {"$inc": {"profile_views": 1}})
    products = list(col("products").find({"artisan_id": a["_id"], "status": "In Stock"}))
    workshops = list(col("workshops").find({"artisan_id": a["_id"], "status": "open"}))
    data = serialize_doc(a)
    data["products"] = [serialize_doc(p) for p in products]
    data["workshops"] = [serialize_doc(w) for w in workshops]
    data["gemScore"] = hidden_gem_score(a)
    return jsonify(data)


# ── Products ──────────────────────────────────────────────────────────────────

@api.get("/products")
def list_products():
    category = request.args.get("category", "")
    state = request.args.get("state", "")
    filt = {"status": "In Stock"}
    if category:
        filt["category"] = {"$regex": category, "$options": "i"}
    if state:
        filt["state"] = {"$regex": state, "$options": "i"}
    limit = min(int(request.args.get("limit", 200)), 500)
    products = list(col("products").find(filt).limit(limit))
    out = []
    for p in products:
        doc = serialize_doc(p)
        artisan = col("artisans").find_one({"_id": p.get("artisan_id")}, {"name": 1})
        if artisan:
            doc["artisan_name"] = artisan.get("name")
        out.append(doc)
    return jsonify(out)


@api.get("/products/<product_id>")
def get_product(product_id):
    p = col("products").find_one({"_id": oid(product_id)})
    if not p:
        return jsonify({"error": "Product not found"}), 404
    artisan = col("artisans").find_one({"_id": p.get("artisan_id")})
    data = serialize_doc(p)
    if artisan:
        data["artisan"] = serialize_doc(artisan)
    return jsonify(data)


# ── Workshops ─────────────────────────────────────────────────────────────────

@api.get("/workshops")
def list_workshops():
    filt = {"status": "open"}
    category = request.args.get("category", "")
    state = request.args.get("state", "")
    if category:
        filt["category"] = {"$regex": category, "$options": "i"}
    if state:
        filt["state"] = {"$regex": state, "$options": "i"}
    limit = min(int(request.args.get("limit", 200)), 500)
    workshops = list(col("workshops").find(filt).limit(limit))
    return jsonify([serialize_doc(w) for w in workshops])


@api.get("/workshops/<workshop_id>")
def get_workshop(workshop_id):
    from auth import get_current_user

    w = col("workshops").find_one({"_id": oid(workshop_id)})
    if not w:
        return jsonify({"error": "Workshop not found"}), 404
    data = serialize_doc(w)
    taken = col("workshop_registrations").count_documents({"workshop_id": w["_id"]})
    total = w.get("seats", 20)
    data["seatsTotal"] = total
    data["seatsRegistered"] = taken
    data["seatsAvailable"] = max(0, total - taken)
    data["seatsAvailable"] = data["seatsAvailable"]  # legacy alias
    data["reviews"] = w.get("reviews", [])
    data["sessions"] = w.get("sessions", [{"id": "session-1", "date": w["date"], "time": w["time"]}])
    user = get_current_user()
    if user:
        data["isRegistered"] = (
            col("workshop_registrations").count_documents({"user_id": user["_id"], "workshop_id": w["_id"]}) > 0
        )
    else:
        data["isRegistered"] = False
    return jsonify(data)


# ── Map & geospatial ──────────────────────────────────────────────────────────

@api.get("/map/regions")
def map_regions():
    regions = list(col("regions").find())
    pins = []
    for r in regions:
        coords = r.get("location", {}).get("coordinates", [0, 0])
        count = col("artisans").count_documents({"state": r["state"], "status": "active"})
        lead = col("artisans").find_one({"state": r["state"], "status": "active"})
        pins.append(
            {
                "id": str(r["_id"]),
                "name": r["name"],
                "state": r["state"],
                "zone": r.get("zone", ""),
                "category": r.get("highlight_craft", ""),
                "craft": r.get("highlight_craft", ""),
                "info": r.get("culture_summary", ""),
                "image": r.get("image", ""),
                "count": count,
                "artisan": lead["name"] if lead else "",
                "lng": coords[0],
                "lat": coords[1],
            }
        )
    return jsonify(pins)


@api.get("/map/nearby")
def map_nearby():
    try:
        lat = float(request.args.get("lat", 0))
        lng = float(request.args.get("lng", 0))
        km = float(request.args.get("km", 25))
    except ValueError:
        return jsonify({"error": "lat, lng, km must be numbers"}), 400
    entity = request.args.get("type", "artisan")
    limit = min(int(request.args.get("limit", 20)), 50)

    collection_map = {"artisan": "artisans", "workshop": "workshops", "region": "regions"}
    collection = collection_map.get(entity, "artisans")
    filt = {"status": "active"} if entity == "artisan" else {"status": "open"} if entity == "workshop" else {}

    items = list(
        col(collection).find(
            {
                **filt,
                "location": {
                    "$near": {
                        "$geometry": point(lng, lat),
                        "$maxDistance": km * 1000,
                    }
                },
            }
        ).limit(limit)
    )

    out = []
    for item in items:
        doc = serialize_doc(item)
        coords = item.get("location", {}).get("coordinates", [lng, lat])
        from math import atan2, cos, radians, sin, sqrt

        dlat = radians(coords[1] - lat)
        dlng = radians(coords[0] - lng)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(coords[1])) * sin(dlng / 2) ** 2
        dist_km = 6371 * 2 * atan2(sqrt(a), sqrt(1 - a))
        doc["distance"] = f"{dist_km:.1f} km"
        doc["distanceKm"] = round(dist_km, 1)
        if entity == "artisan":
            doc["craft"] = item.get("category")
            doc["snippet"] = item.get("bio", "")[:120]
        out.append(doc)
    return jsonify(out)


@api.get("/regions/<state>")
def region_page(state):
    region = col("regions").find_one({"state": {"$regex": f"^{state}$", "$options": "i"}})
    if not region:
        return jsonify({"error": "Region not found"}), 404
    st = region["state"]
    workshops = list(col("workshops").find({"state": st, "status": "open"}).limit(10))
    products_raw = list(col("products").find({"state": st, "status": "In Stock"}).limit(10))
    products = []
    for p in products_raw:
        doc = serialize_doc(p)
        artisan = col("artisans").find_one({"_id": p.get("artisan_id")}, {"name": 1})
        if artisan:
            doc["artisan_name"] = artisan.get("name")
        products.append(doc)
    artisans = list(col("artisans").find({"state": st, "status": "active"}).limit(10))
    return jsonify(
        {
            "region": serialize_doc(region),
            "culture": region.get("culture", {}),
            "workshops": [serialize_doc(w) for w in workshops],
            "products": products,
            "artisans": [serialize_doc(a) for a in artisans],
            "cuisine": region.get("cuisine", []),
        }
    )


@api.get("/discover/hidden-gems")
def hidden_gems():
    limit = min(int(request.args.get("limit", 10)), 30)
    entity = request.args.get("type", "artisan")
    collection = {"artisan": "artisans", "product": "products", "workshop": "workshops"}.get(entity, "artisans")
    filt = {"status": "active"} if entity == "artisan" else {"status": "In Stock"} if entity == "product" else {"status": "open"}
    items = list(col(collection).find(filt))
    ranked = sorted(items, key=hidden_gem_score, reverse=True)[:limit]
    return jsonify([{**serialize_doc(i), "gemScore": hidden_gem_score(i)} for i in ranked])


# ── Artisan application ───────────────────────────────────────────────────────

@api.post("/artisan/apply")
@login_required
def artisan_apply(user):
    if user.get("role") == "artisan":
        return jsonify({"error": "Already an artisan"}), 400
    existing = col("artisan_applications").find_one({"user_id": user["_id"]})
    if existing and existing.get("status") == "pending":
        return jsonify({"error": "Application already pending"}), 409

    state = (request.form.get("state") or "").strip()
    region = (request.form.get("region") or user.get("geographic_focus") or "").strip()
    description = (request.form.get("description") or "").strip()

    crafts_raw = request.form.get("crafts") or request.form.get("craftCategories") or ""
    crafts: list[str] = []
    if crafts_raw.strip().startswith("["):
        import json

        try:
            parsed = json.loads(crafts_raw)
            if isinstance(parsed, list):
                crafts = [str(c).strip() for c in parsed if str(c).strip()]
        except json.JSONDecodeError:
            crafts = []
    elif crafts_raw:
        crafts = [c.strip() for c in crafts_raw.split(",") if c.strip()]
    else:
        for c in request.form.getlist("crafts"):
            if c.strip() and not c.strip().startswith("["):
                crafts.append(c.strip())
    craft_single = (request.form.get("craftCategory") or request.form.get("category") or "").strip()
    if craft_single and "," not in craft_single and craft_single not in crafts:
        crafts.insert(0, craft_single)
    # Deduplicate while preserving order
    seen: set[str] = set()
    crafts = [c for c in crafts if not (c in seen or seen.add(c))]

    if not state:
        return jsonify({"error": "state required"}), 400
    if not crafts:
        return jsonify({"error": "At least one craft required"}), 400

    region_validation = validate_application_crafts(state, crafts)
    if not region_validation.get("valid"):
        return jsonify({"error": region_validation.get("error", "Invalid application")}), 400

    normalized_state = region_validation["state"]
    if not region:
        region = f"{normalized_state}, India"

    try:
        govt_url = save_upload(request.files.get("govtId"), "applications")
        cert_url = save_upload(request.files.get("cert"), "applications")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    portfolio = []
    for key in request.files:
        if key.startswith("portfolio"):
            try:
                url = save_upload(request.files[key], "applications")
                if url:
                    portfolio.append(url)
            except ValueError:
                pass
    for url in request.form.getlist("portfolioUrls"):
        if url:
            portfolio.append(url)

    app_doc = {
        "user_id": user["_id"],
        "name": user["name"],
        "email": user["email"],
        "state": normalized_state,
        "crafts": crafts,
        "category": ", ".join(crafts),
        "region": region,
        "description": description,
        "craft_icon": request.form.get("craftIcon", "brush"),
        "govt_id_url": govt_url,
        "cert_url": cert_url,
        "portfolio": portfolio,
        "region_validation": region_validation,
        "status": "pending",
        "curator_notes": "",
        "reviewed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    col("artisan_applications").update_one({"user_id": user["_id"]}, {"$set": app_doc}, upsert=True)
    return jsonify({"status": "pending", "message": "Application submitted", "regionValidation": region_validation}), 201


@api.get("/artisan/application/status")
@login_required
def application_status(user):
    app_doc = col("artisan_applications").find_one({"user_id": user["_id"]})
    if not app_doc:
        return jsonify({"status": "none"})
    return jsonify(
        {
            "id": str(app_doc["_id"]),
            "status": app_doc["status"],
            "category": app_doc.get("category"),
            "crafts": app_doc.get("crafts", []),
            "state": app_doc.get("state", ""),
            "region": app_doc.get("region"),
            "regionValidation": app_doc.get("region_validation"),
            "curatorNotes": app_doc.get("curator_notes", ""),
            "date": dt_strftime(app_doc.get("created_at")),
            "reviewedAt": dt_strftime(app_doc.get("reviewed_at"))
            if app_doc.get("reviewed_at")
            else "",
        }
    )


# ── Artisan dashboard ───────────────────────────────────────────────────────────

def _get_artisan_profile(user):
    return col("artisans").find_one({"user_id": user["_id"]})


@api.get("/artisan/profile")
@role_required("artisan")
def artisan_get_profile(user):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Artisan profile not found"}), 404
    return jsonify(serialize_doc(profile))


@api.patch("/artisan/profile")
@role_required("artisan")
def artisan_update_profile(user):
    data = request.get_json(silent=True) or {}
    allowed = {"name", "bio", "category", "region", "state", "avatar", "highlightImage", "tag", "studioName", "studioBio", "payoutUPI", "studioLocation"}
    updates = {}
    field_map = {"highlightImage": "highlight_image", "studioName": "studio_name", "studioBio": "studio_bio", "payoutUPI": "payout_upi", "studioLocation": "studio_location"}
    for k, v in data.items():
        key = field_map.get(k, k)
        if key in allowed or k in allowed:
            updates[field_map.get(k, k)] = v
    if "lat" in data and "lng" in data:
        updates["location"] = point(float(data["lng"]), float(data["lat"]))
    col("artisans").update_one({"user_id": user["_id"]}, {"$set": updates})
    profile = _get_artisan_profile(user)
    return jsonify(serialize_doc(profile))


@api.post("/artisan/profile/portfolio")
@role_required("artisan")
def artisan_upload_portfolio(user):
    file = request.files.get("portfolio") or request.files.get("file")
    if not file:
        return jsonify({"error": "portfolio file required"}), 400
    try:
        url = save_upload(file, "portfolio")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    col("artisans").update_one(
        {"user_id": user["_id"]},
        {"$set": {"highlight_image": url, "portfolio_image": url}},
    )
    return jsonify({"url": url, "highlightImage": url})


@api.get("/artisan/products")
@role_required("artisan")
def artisan_list_products(user):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    products = list(col("products").find({"artisan_id": profile["_id"]}))
    return jsonify([serialize_doc(p) for p in products])


@api.post("/artisan/products")
@role_required("artisan")
def artisan_add_product(user):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    data = request.get_json(silent=True) or {}
    craft = (data.get("craft") or data.get("craftName") or "").strip()
    category = data.get("category") or infer_product_category(craft)
    if not craft:
        return jsonify({"error": "craft required — must match your approved application crafts"}), 400
    if not artisan_craft_allowed(profile, craft, category):
        approved = profile.get("approved_crafts") or [profile.get("category", "")]
        return jsonify(
            {
                "error": "Craft not in your approved list",
                "approvedCrafts": approved,
            }
        ), 403
    price_str = str(data.get("price", "0")).replace("₹", "").replace(",", "")
    try:
        price_num = float(re.sub(r"[^\d.]", "", price_str) or 0)
    except ValueError:
        price_num = 0
    artisan_state = profile.get("state", "")
    product = {
        "artisan_id": profile["_id"],
        "name": data.get("name") or data.get("title"),
        "description": data.get("description", ""),
        "price_num": price_num,
        "price_display": data.get("price", f"₹{price_num:,.0f}"),
        "category": category,
        "craft": craft,
        "image": data.get("image", ""),
        "state": artisan_state,
        "status": data.get("status", "In Stock"),
        "popularity": 70,
        "rating": 4.2,
        "regional_uniqueness": 7.0,
        "created_at": datetime.now(timezone.utc),
    }
    result = col("products").insert_one(product)
    product["_id"] = result.inserted_id
    return jsonify(serialize_doc(product)), 201


@api.patch("/artisan/products/<product_id>")
@role_required("artisan")
def artisan_update_product(user, product_id):
    profile = _get_artisan_profile(user)
    p_oid = oid(product_id)
    product = col("products").find_one({"_id": p_oid, "artisan_id": profile["_id"]})
    if not product:
        return jsonify({"error": "Product not found"}), 404
    data = request.get_json(silent=True) or {}
    updates = {k: v for k, v in data.items() if k in {"name", "description", "price", "category", "image", "status", "craft"}}
    craft = updates.get("craft")
    if craft and not artisan_craft_allowed(profile, craft, updates.get("category", "")):
        return jsonify({"error": "Craft not in your approved list"}), 403
    if "price" in updates:
        price_str = str(updates["price"]).replace("₹", "").replace(",", "")
        updates["price_num"] = float(re.sub(r"[^\d.]", "", price_str) or 0)
        updates["price_display"] = updates.pop("price")
    col("products").update_one({"_id": p_oid}, {"$set": updates})
    return jsonify(serialize_doc(col("products").find_one({"_id": p_oid})))


@api.delete("/artisan/products/<product_id>")
@role_required("artisan")
def artisan_delete_product(user, product_id):
    profile = _get_artisan_profile(user)
    result = col("products").delete_one({"_id": oid(product_id), "artisan_id": profile["_id"]})
    if result.deleted_count == 0:
        return jsonify({"error": "Product not found"}), 404
    return jsonify({"success": True})


@api.get("/artisan/workshops")
@role_required("artisan")
def artisan_list_workshops(user):
    profile = _get_artisan_profile(user)
    workshops = list(col("workshops").find({"artisan_id": profile["_id"]}))
    return jsonify([serialize_doc(w) for w in workshops])


@api.post("/artisan/workshops")
@role_required("artisan")
def artisan_add_workshop(user):
    profile = _get_artisan_profile(user)
    data = request.get_json(silent=True) or {}
    craft = (data.get("craft") or data.get("craftName") or data.get("title") or "").strip()
    category = data.get("category", "Hands-on")
    if not craft:
        return jsonify({"error": "craft required — must match your approved application crafts"}), 400
    if not artisan_craft_allowed(profile, craft, category):
        approved = profile.get("approved_crafts") or [profile.get("category", "")]
        return jsonify({"error": "Craft not in your approved list", "approvedCrafts": approved}), 403
    price_str = str(data.get("price", "0")).replace("₹", "").replace(",", "")
    price_num = float(re.sub(r"[^\d.]", "", price_str) or 0)
    artisan_state = profile.get("state", "")
    lng, lat = state_coordinates(artisan_state)
    workshop = {
        "artisan_id": profile["_id"],
        "title": data.get("title") or data.get("workshopName"),
        "instructor": profile.get("name", user["name"]),
        "instructor_avatar": profile.get("avatar", ""),
        "date": data.get("date", ""),
        "time": data.get("time", ""),
        "price": price_num,
        "price_display": data.get("price", f"₹{price_num:,.0f}"),
        "category": category,
        "craft": craft,
        "thumbnail": data.get("thumbnail", ""),
        "venue": data.get("venue", ""),
        "seats": int(data.get("seats", 20)),
        "mode": data.get("mode", "offline"),
        "state": artisan_state,
        "status": "open",
        "location": profile.get("location") or point(lng, lat),
        "registration_count": 0,
        "popularity": 60,
        "rating": 4.5,
        "regional_uniqueness": 8.0,
        "created_at": datetime.now(timezone.utc),
    }
    result = col("workshops").insert_one(workshop)
    workshop["_id"] = result.inserted_id
    return jsonify(serialize_doc(workshop)), 201


@api.patch("/artisan/workshops/<workshop_id>")
@role_required("artisan")
def artisan_update_workshop(user, workshop_id):
    profile = _get_artisan_profile(user)
    w_oid = oid(workshop_id)
    if not col("workshops").find_one({"_id": w_oid, "artisan_id": profile["_id"]}):
        return jsonify({"error": "Workshop not found"}), 404
    data = request.get_json(silent=True) or {}
    allowed = {"title", "date", "time", "price", "category", "thumbnail", "venue", "seats", "mode", "status"}
    updates = {k: v for k, v in data.items() if k in allowed}
    col("workshops").update_one({"_id": w_oid}, {"$set": updates})
    return jsonify(serialize_doc(col("workshops").find_one({"_id": w_oid})))


@api.delete("/artisan/workshops/<workshop_id>")
@role_required("artisan")
def artisan_delete_workshop(user, workshop_id):
    profile = _get_artisan_profile(user)
    w_oid = oid(workshop_id)
    result = col("workshops").delete_one({"_id": w_oid, "artisan_id": profile["_id"]})
    if result.deleted_count == 0:
        return jsonify({"error": "Workshop not found"}), 404
    col("workshop_registrations").delete_many({"workshop_id": w_oid})
    return jsonify({"success": True})


@api.get("/artisan/analytics")
@role_required("artisan")
def artisan_analytics(user):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    aid = profile["_id"]
    workshop_ids = [w["_id"] for w in col("workshops").find({"artisan_id": aid}, {"_id": 1})]
    reg_count = col("workshop_registrations").count_documents({"workshop_id": {"$in": workshop_ids}}) if workshop_ids else 0
    products_purchased = col("orders").count_documents({"artisan_id": aid})
    products_viewed = sum(
        p.get("view_count", 0) for p in col("products").find({"artisan_id": aid}, {"view_count": 1})
    )
    return jsonify(
        {
            "workshopRegistrations": reg_count,
            "productsPurchased": products_purchased,
            "productsViewed": products_viewed,
        }
    )


@api.get("/artisan/registrations")
@role_required("artisan")
def artisan_workshop_registrations(user):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    workshop_ids = [w["_id"] for w in col("workshops").find({"artisan_id": profile["_id"]}, {"_id": 1})]
    if not workshop_ids:
        return jsonify([])
    regs = list(
        col("workshop_registrations")
        .find({"workshop_id": {"$in": workshop_ids}})
        .sort("created_at", -1)
    )
    out = []
    for r in regs:
        ws = col("workshops").find_one({"_id": r["workshop_id"]})
        u = col("users").find_one({"_id": r["user_id"]})
        if not ws:
            continue
        status = r.get("status", "Confirmed")
        if r.get("attended"):
            status = "Completed"
        out.append(
            {
                "id": str(r["_id"]),
                "student": u.get("name", "Guest") if u else "Guest",
                "course": ws.get("title"),
                "date": ws.get("date"),
                "time": ws.get("time"),
                "seats": 1,
                "status": status,
            }
        )
    return jsonify(out)


@api.patch("/artisan/registrations/<registration_id>")
@role_required("artisan")
def update_artisan_registration(user, registration_id):
    profile = _get_artisan_profile(user)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404
    reg_oid = oid(registration_id)
    if not reg_oid:
        return jsonify({"error": "Invalid registration id"}), 400
    reg = col("workshop_registrations").find_one({"_id": reg_oid})
    if not reg:
        return jsonify({"error": "Registration not found"}), 404
    ws = col("workshops").find_one({"_id": reg["workshop_id"]})
    if not ws or ws.get("artisan_id") != profile["_id"]:
        return jsonify({"error": "Not allowed"}), 403

    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "Confirmed").strip()
    allowed = {"Confirmed", "Pending", "Completed", "Registration Submitted"}
    if new_status not in allowed:
        return jsonify({"error": "Invalid status"}), 400

    if new_status in ("Completed", "Attended"):
        new_status = "Completed"

    update_fields = {"status": new_status, "updated_at": datetime.now(timezone.utc)}
    if new_status == "Completed":
        update_fields["attended"] = True

    col("workshop_registrations").update_one({"_id": reg_oid}, {"$set": update_fields})

    if new_status == "Confirmed":
        push_notification(
            reg["user_id"],
            "workshop",
            "Workshop Seat Confirmed",
            f'Your seat is confirmed for "{ws.get("title", "workshop")}" on {ws.get("date", "TBD")} at {ws.get("time", "TBD")}.',
            {"workshopId": str(ws["_id"]), "registrationId": str(reg_oid)},
        )
    elif new_status == "Completed":
        push_notification(
            reg["user_id"],
            "workshop",
            "Workshop Completed",
            f'Your session for "{ws.get("title", "workshop")}" is marked complete. View it under Attended Workshops in your profile.',
            {"workshopId": str(ws["_id"]), "registrationId": str(reg_oid)},
        )

    return jsonify({"success": True, "status": new_status})


# ── Admin ─────────────────────────────────────────────────────────────────────

@api.get("/admin/analytics")
@role_required("admin")
def admin_analytics(user):
    from india_data import STATE_ZONE

    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    now = datetime.now(timezone.utc)

    month_counts: dict[str, int] = {m: 0 for m in month_labels}
    for reg in col("workshop_registrations").find({}, {"created_at": 1}):
        created = as_datetime(reg.get("created_at"))
        if created:
            month_counts[month_labels[created.month - 1]] += 1

    if col("workshop_registrations").count_documents({}) == 0:
        for ws in col("workshops").find({}, {"registration_count": 1, "created_at": 1}):
            created = as_datetime(ws.get("created_at")) or now
            month_counts[month_labels[created.month - 1]] += ws.get("registration_count", 0)

    monthly_trends = []
    for i in range(5, -1, -1):
        idx = (now.month - 1 - i) % 12
        label = month_labels[idx]
        value = month_counts.get(label, 0)
        monthly_trends.append({"label": label, "value": value})
    max_trend = max((t["value"] for t in monthly_trends), default=1) or 1
    for t in monthly_trends:
        t["heightPct"] = round(t["value"] / max_trend * 100)

    # Heritage-focused metrics
    explored_state = list(
        col("orders").aggregate(
            [
                {"$lookup": {"from": "products", "localField": "product_id", "foreignField": "_id", "as": "p"}},
                {"$unwind": "$p"},
                {"$group": {"_id": "$p.state", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 1},
            ]
        )
    )
    if not explored_state:
        explored_state = list(
            col("artisans").aggregate([{"$group": {"_id": "$state", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 1}])
        )
    most_explored_state = explored_state[0]["_id"] if explored_state else "—"

    ws_by_state = list(
        col("workshop_registrations").aggregate(
            [
                {"$lookup": {"from": "workshops", "localField": "workshop_id", "foreignField": "_id", "as": "w"}},
                {"$unwind": "$w"},
                {"$group": {"_id": "$w.state", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 1},
            ]
        )
    )
    top_ws_state = ws_by_state[0]["_id"] if ws_by_state else most_explored_state
    most_explored_region = STATE_ZONE.get(most_explored_state, STATE_ZONE.get(top_ws_state, "—"))

    category_liked = list(
        col("products").aggregate(
            [{"$group": {"_id": "$category", "score": {"$sum": {"$add": ["$save_count", "$view_count", "$order_count"]}}}}, {"$sort": {"score": -1}}, {"$limit": 1}]
        )
    )
    most_liked_category = category_liked[0]["_id"] if category_liked else "—"

    trending_craft = list(
        col("products").aggregate(
            [{"$group": {"_id": "$craft", "views": {"$sum": "$view_count"}}}, {"$sort": {"views": -1}}, {"$limit": 1}]
        )
    )
    trending_craft_name = trending_craft[0]["_id"] if trending_craft else "Traditional crafts"

    engagement_state = list(
        col("artisans").aggregate(
            [{"$group": {"_id": "$state", "engagement": {"$sum": {"$add": ["$profile_views", "$save_count", "$popularity"]}}}}, {"$sort": {"engagement": -1}}, {"$limit": 1}]
        )
    )
    top_engagement_state = engagement_state[0]["_id"] if engagement_state else most_explored_state

    most_workshop = list(col("workshops").find().sort("registration_count", -1).limit(1))
    approved_artisans = list(
        col("artisans").find({"status": "active"}).sort("created_at", -1).limit(50)
    )
    clusters = col("artisans").count_documents({"status": "active"})

    insight_cards = [
        f"{trending_craft_name} is trending this month",
        f"{top_ws_state} generated highest workshop registrations",
        f"{top_engagement_state} has highest artisan engagement",
    ]

    return jsonify(
        {
            "totalUsers": col("users").count_documents({"role": "user"}),
            "totalArtisans": clusters,
            "totalProducts": col("products").count_documents({}),
            "totalWorkshops": col("workshops").count_documents({}),
            "pendingApplications": col("artisan_applications").count_documents({"status": "pending"}),
            "approvedApplications": col("artisan_applications").count_documents({"status": "approved"}),
            "mostExploredState": most_explored_state,
            "mostExploredRegion": most_explored_region,
            "mostLikedCategory": most_liked_category,
            "mostSavedArtisan": list(col("artisans").find().sort("save_count", -1).limit(1))[0]["name"] if col("artisans").count_documents({}) else "—",
            "mostRegisteredWorkshop": most_workshop[0]["title"] if most_workshop else "—",
            "totalOrders": col("orders").count_documents({}),
            "totalWorkshopRegistrations": col("workshop_registrations").count_documents({}),
            "artisanClusters": clusters,
            "monthlyTrends": monthly_trends,
            "approvedArtisans": [
                {
                    "id": str(a["_id"]),
                    "name": a.get("name"),
                    "state": a.get("state"),
                    "category": a.get("category"),
                    "crafts": a.get("approved_crafts") or a.get("crafts") or [],
                }
                for a in approved_artisans
            ],
            "insightCards": insight_cards,
        }
    )


def _serialize_application(a: dict) -> dict:
    rv = a.get("region_validation") or {}
    if not rv and a.get("state") and a.get("crafts"):
        rv = validate_application_crafts(a["state"], a.get("crafts", []))
    return {
        "id": str(a["_id"]),
        "name": a["name"],
        "email": a["email"],
        "category": a.get("category", ""),
        "crafts": a.get("crafts", []),
        "state": a.get("state", ""),
        "region": a.get("region", ""),
        "description": a.get("description", ""),
        "craftIcon": a.get("craft_icon", "brush"),
        "date": dt_strftime(a.get("created_at")),
        "status": a["status"],
        "govtIdUrl": a.get("govt_id_url", ""),
        "certUrl": a.get("cert_url", ""),
        "portfolio": a.get("portfolio", []),
        "regionValidation": rv,
    }


@api.get("/admin/applications")
@role_required("admin")
def admin_applications(user):
    status = request.args.get("status", "pending")
    filt = {"status": status} if status != "all" else {}
    apps = list(col("artisan_applications").find(filt).sort("created_at", -1))
    return jsonify([_serialize_application(a) for a in apps])


@api.get("/admin/applications/<app_id>")
@role_required("admin")
def admin_application_detail(user, app_id):
    a = col("artisan_applications").find_one({"_id": oid(app_id)})
    if not a:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize_application(a))


@api.patch("/admin/applications/<app_id>")
@role_required("admin")
def admin_review_application(user, app_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"approved", "rejected", "pending"}:
        return jsonify({"error": "status must be approved|rejected|pending"}), 400
    a_oid = oid(app_id)
    app_doc = col("artisan_applications").find_one({"_id": a_oid})
    if not app_doc:
        return jsonify({"error": "Application not found"}), 404

    col("artisan_applications").update_one(
        {"_id": a_oid},
        {"$set": {"status": status, "curator_notes": data.get("curatorNotes", ""), "reviewed_at": datetime.now(timezone.utc)}},
    )

    if status == "approved":
        col("users").update_one({"_id": app_doc["user_id"]}, {"$set": {"role": "artisan"}})
        push_notification(
            app_doc["user_id"],
            "application",
            "Application Approved",
            "Your artisan application has been approved. You can now access the Artisan Dashboard.",
            {"applicationId": str(a_oid)},
        )
        crafts = app_doc.get("crafts") or ([app_doc["category"]] if app_doc.get("category") else [])
        state = app_doc.get("state") or normalize_state(app_doc.get("region", "")) or "India"
        if state == "India" and app_doc.get("region"):
            state = app_doc.get("region", "").split(",")[-1].strip().replace(" India", "")
        lng, lat = state_coordinates(state)
        artisan = {
            "user_id": app_doc["user_id"],
            "name": app_doc["name"],
            "email": app_doc["email"],
            "category": app_doc.get("category", ""),
            "approved_crafts": crafts,
            "crafts": crafts,
            "region": app_doc.get("region", f"{state}, India"),
            "state": state,
            "bio": app_doc.get("description", ""),
            "avatar": app_doc.get("portfolio", [""])[0] if app_doc.get("portfolio") else "",
            "highlight_image": app_doc.get("portfolio", [""])[0] if app_doc.get("portfolio") else "",
            "tag": "Next Gen",
            "status": "active",
            "rating": 4.0,
            "popularity": 75,
            "regional_uniqueness": 8.0,
            "profile_views": 0,
            "follower_count": 0,
            "save_count": 0,
            "location": point(lng, lat),
            "created_at": datetime.now(timezone.utc),
        }
        col("artisans").update_one({"user_id": app_doc["user_id"]}, {"$set": artisan}, upsert=True)

    if status == "rejected":
        notes = (data.get("curatorNotes") or "").strip()
        msg = (
            f"Your application was not approved. Curator note: {notes}"
            if notes
            else "Your artisan application was not approved. You may update your portfolio and reapply."
        )
        push_notification(
            app_doc["user_id"],
            "application",
            "Application Rejected",
            msg,
            {"applicationId": str(a_oid)},
        )

    return jsonify({"success": True, "status": status})


@api.get("/admin/users")
@role_required("admin")
def admin_users(user):
    users = list(col("users").find({"role": {"$in": ["user", "artisan"]}}).sort("created_at", -1).limit(100))
    return jsonify(
        [
            {
                "id": str(u["_id"]),
                "name": u["name"],
                "email": u["email"],
                "interests": ", ".join(u.get("interests", [])),
                "status": "Blocked" if u.get("status") == "blocked" else "Active",
                "joined": dt_strftime(u.get("created_at")),
                "role": u.get("role", "user"),
            }
            for u in users
        ]
    )


@api.patch("/admin/users/<user_id>/status")
@role_required("admin")
def admin_user_status(user, user_id):
    data = request.get_json(silent=True) or {}
    status = "blocked" if data.get("status") == "Blocked" else "active"
    col("users").update_one({"_id": oid(user_id)}, {"$set": {"status": status}})
    return jsonify({"success": True})


@api.get("/admin/artisans")
@role_required("admin")
def admin_artisans(user):
    artisans = list(col("artisans").find().sort("created_at", -1))
    return jsonify(
        [
            {
                "id": str(a["_id"]),
                "name": a["name"],
                "region": a.get("region", ""),
                "category": a.get("category", ""),
                "status": "Active" if a.get("status") == "active" else "Suspended",
                "sales": f"₹{a.get('sales_total', 0):,}",
            }
            for a in artisans
        ]
    )


@api.patch("/admin/artisans/<artisan_id>/status")
@role_required("admin")
def admin_artisan_status(user, artisan_id):
    data = request.get_json(silent=True) or {}
    status = "active" if data.get("status") == "Active" else "suspended"
    col("artisans").update_one({"_id": oid(artisan_id)}, {"$set": {"status": status}})
    return jsonify({"success": True})


@api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "Hidden India Explorer API"})
