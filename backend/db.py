import json
import re
import threading
from datetime import datetime, timezone
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from ids import new_id

_client = None
_db = None
_connection_error: Exception | None = None
_connection_params: dict[str, Any] | None = None
_db_lock = threading.RLock()

DEFAULT_DB_NAME = "hidden_india"


class Query:
    def __init__(self, collection: "Collection", filter_: dict | None = None, projection: dict | None = None):
        self.collection = collection
        self.filter = filter_ or {}
        self.projection = projection or {}
        self.sort_fields: list[tuple[str, int]] = []
        self.limit_value: int | None = None

    def sort(self, field: str, direction: int = 1):
        self.sort_fields.append((field, direction))
        return self

    def limit(self, value: int):
        self.limit_value = value
        return self

    def _execute(self) -> list[dict]:
        docs = self.collection._find_documents(self.filter)
        if self.sort_fields:
            for field, direction in reversed(self.sort_fields):
                docs = sorted(docs, key=lambda doc: _sort_value(doc.get(field)), reverse=direction < 0)
        if self.limit_value is not None:
            docs = docs[: self.limit_value]
        return [self.collection._project(doc) for doc in docs]

    def __iter__(self):
        return iter(self._execute())

    def __len__(self):
        return len(self._execute())


class Collection:
    def __init__(self, name: str):
        self.name = name

    def _project(self, doc: dict) -> dict:
        projection = self._projection_fields()
        if not projection:
            return doc
        projected = {}
        for key, value in doc.items():
            if key in projection:
                projected[key] = value
        return projected

    def _projection_fields(self) -> set[str]:
        return set()

    def _find_documents(self, filter_: dict | None = None) -> list[dict]:
        with _db_lock:
            if not _ensure_connection():
                return []
            _ensure_schema()
            try:
                cursor = _client.cursor(dictionary=True)
                try:
                    cursor.execute("SELECT data FROM generic_documents WHERE collection_name = %s", (self.name,))
                    rows = cursor.fetchall()
                finally:
                    cursor.close()
            except MySQLError:
                _drop_connection()
                if not _ensure_connection():
                    return []
                cursor = _client.cursor(dictionary=True)
                try:
                    cursor.execute("SELECT data FROM generic_documents WHERE collection_name = %s", (self.name,))
                    rows = cursor.fetchall()
                finally:
                    cursor.close()
            docs = []
            for row in rows:
                doc = json.loads(row["data"])
                if _matches_filter(doc, filter_ or {}):
                    docs.append(doc)
            return docs

    def find_one(self, filter_: dict | None = None, projection: dict | None = None):
        docs = self._find_documents(filter_)
        if not docs:
            return None
        doc = docs[0]
        return self._project(doc) if projection else doc

    def find(self, filter_: dict | None = None, projection: dict | None = None):
        return Query(self, filter_, projection)

    def insert_one(self, doc: dict):
        doc = _normalize_document(self.name, doc)
        _insert_document(self.name, doc)
        return type("InsertResult", (), {"inserted_id": doc.get("_id")})()

    def insert_many(self, docs: list[dict]):
        for doc in docs:
            self.insert_one(doc)
        return type("InsertManyResult", (), {"inserted_ids": [doc.get("_id") for doc in docs]})()

    def update_one(self, filter_: dict | None, update: dict, upsert: bool = False):
        doc = self.find_one(filter_)
        if not doc and upsert:
            doc = _normalize_document(self.name, _doc_from_filter(filter_ or {}))
        if not doc:
            return type("UpdateResult", (), {"matched_count": 0, "modified_count": 0})()
        if "$set" in update:
            for key, value in update["$set"].items():
                doc[key] = value
        if "$inc" in update:
            for key, value in update["$inc"].items():
                doc[key] = (doc.get(key, 0) or 0) + value
        if not doc.get("_id"):
            doc = _normalize_document(self.name, doc)
        doc["updated_at"] = datetime.now(timezone.utc)
        _replace_document(self.name, doc)
        return type("UpdateResult", (), {"matched_count": 1, "modified_count": 1})()

    def delete_one(self, filter_: dict | None):
        docs = self._find_documents(filter_)
        if not docs:
            return type("DeleteResult", (), {"deleted_count": 0})()
        doc = docs[0]
        _delete_document(self.name, doc.get("_id"))
        return type("DeleteResult", (), {"deleted_count": 1})()

    def delete_many(self, filter_: dict | None):
        docs = self._find_documents(filter_)
        for doc in docs:
            _delete_document(self.name, doc.get("_id"))
        return type("DeleteResult", (), {"deleted_count": len(docs)})()

    def count_documents(self, filter_: dict | None = None):
        return len(self._find_documents(filter_))

    def aggregate(self, pipeline: list[dict]):
        docs = self._find_documents({})
        for step in pipeline:
            if "$lookup" in step:
                lookup = step["$lookup"]
                foreign = col(lookup["from"])
                local_field = lookup.get("localField")
                foreign_field = lookup.get("foreignField")
                extra_docs = []
                for doc in docs:
                    local_value = doc.get(local_field)
                    related = [item for item in foreign._find_documents({}) if item.get(foreign_field) == local_value]
                    if related:
                        new_doc = dict(doc)
                        new_doc[lookup.get("as", "joined")] = related
                        extra_docs.append(new_doc)
                    else:
                        new_doc = dict(doc)
                        new_doc[lookup.get("as", "joined")] = []
                        extra_docs.append(new_doc)
                docs = extra_docs
            elif "$unwind" in step:
                field = step["$unwind"]
                if not isinstance(field, str):
                    continue
                expanded = []
                for doc in docs:
                    values = doc.get(field, [])
                    if isinstance(values, list) and values:
                        for item in values:
                            child = dict(doc)
                            child[field] = item
                            expanded.append(child)
                    else:
                        expanded.append(doc)
                docs = expanded
            elif "$group" in step:
                group = step["$group"]
                _id = group.get("_id")
                if isinstance(_id, str) and _id.startswith("$"):
                    key_name = _id[1:]
                else:
                    key_name = None
                result = []
                buckets: dict[Any, list[dict]] = {}
                for doc in docs:
                    if key_name is None:
                        bucket_key = None
                    else:
                        bucket_key = doc.get(key_name)
                    buckets.setdefault(bucket_key, []).append(doc)
                for key, items in buckets.items():
                    grouped = {"_id": key}
                    for output_name, expr in group.items():
                        if output_name == "_id":
                            continue
                        if isinstance(expr, dict) and "$sum" in expr:
                            raw = expr["$sum"]
                            if isinstance(raw, dict) and "$add" in raw:
                                value = 0
                                for part in raw["$add"]:
                                    if isinstance(part, str) and part.startswith("$"):
                                        value += sum(item.get(part[1:], 0) for item in items)
                                    else:
                                        value += part
                                grouped[output_name] = value
                            elif isinstance(raw, str) and raw.startswith("$"):
                                grouped[output_name] = sum(item.get(raw[1:], 0) for item in items)
                            else:
                                grouped[output_name] = len(items)
                        elif isinstance(expr, str) and expr.startswith("$"):
                            grouped[output_name] = items[0].get(expr[1:]) if items else None
                        else:
                            grouped[output_name] = expr
                    result.append(grouped)
                docs = result
            elif "$sort" in step:
                sort_fields = step["$sort"]
                docs = sorted(docs, key=lambda doc: _sort_value(doc.get(list(sort_fields.keys())[0])), reverse=list(sort_fields.values())[0] < 0)
            elif "$limit" in step:
                docs = docs[: step["$limit"]]
        return docs

    def create_index(self, *args, **kwargs):
        return None


def _doc_from_filter(filter_: dict | None):
    doc = {}
    if not filter_:
        return doc
    for key, value in filter_.items():
        if isinstance(value, dict):
            if "$in" in value:
                doc[key] = value["$in"][0]
            elif "$regex" in value:
                doc[key] = ""
            else:
                doc[key] = None
        else:
            doc[key] = value
    return doc


def _normalize_document(collection_name: str, doc: dict) -> dict:
    normalized = dict(doc)
    if "_id" not in normalized or normalized.get("_id") in (None, ""):
        normalized["_id"] = new_id()
    normalized["_id"] = str(normalized["_id"])
    normalized.setdefault("created_at", datetime.now(timezone.utc))
    normalized.setdefault("updated_at", datetime.now(timezone.utc))
    if collection_name == "users" and "created_at" not in normalized:
        normalized["created_at"] = datetime.now(timezone.utc)
    return normalized


def _insert_document(collection_name: str, doc: dict) -> None:
    with _db_lock:
        if not _ensure_connection():
            return
        _ensure_schema()
        if not doc.get("_id"):
            doc["_id"] = new_id()
        cursor = _client.cursor()
        try:
            cursor.execute(
                "INSERT INTO generic_documents (collection_name, document_id, data, created_at, updated_at) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE data = VALUES(data), updated_at = VALUES(updated_at)",
                (
                    collection_name,
                    str(doc.get("_id")),
                    json.dumps(doc, default=_json_default),
                    doc.get("created_at") or datetime.now(timezone.utc),
                    doc.get("updated_at") or datetime.now(timezone.utc),
                ),
            )
            _client.commit()
        finally:
            cursor.close()


def _replace_document(collection_name: str, doc: dict) -> None:
    _insert_document(collection_name, doc)


def _delete_document(collection_name: str, doc_id: Any) -> None:
    with _db_lock:
        if not _ensure_connection():
            return
        _ensure_schema()
        cursor = _client.cursor()
        try:
            cursor.execute("DELETE FROM generic_documents WHERE collection_name = %s AND document_id = %s", (collection_name, str(doc_id)))
            _client.commit()
        finally:
            cursor.close()


def init_db(uri: str):
    global _client, _db, _connection_error, _connection_params
    from config import normalize_mysql_uri

    uri = normalize_mysql_uri(uri)
    _connection_error = None
    try:
        parsed = _parse_mysql_uri(uri)
        _connection_params = {
            "host": parsed["host"],
            "port": parsed["port"],
            "user": parsed["user"],
            "password": parsed["password"],
            "database": parsed["database"],
            "autocommit": False,
            "use_pure": True,
        }
        _connect()
        _ensure_schema()
        return _db
    except (MySQLError, OSError, ValueError, UnicodeError) as exc:
        _client = None
        _db = None
        _connection_error = exc
        print(f"MySQL unavailable: {exc}")
        return None


def _connect() -> None:
    global _client, _db
    if not _connection_params:
        raise RuntimeError("Database connection params not set")
    params = dict(_connection_params)
    database = params.pop("database")
    # Ensure server is reachable, then select/create database
    bootstrap = mysql.connector.connect(**params)
    try:
        cur = bootstrap.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        bootstrap.commit()
        cur.close()
    finally:
        bootstrap.close()
    params["database"] = database
    _client = mysql.connector.connect(**params)
    _db = _client


def _drop_connection() -> None:
    global _client, _db
    try:
        if _client:
            _client.close()
    except Exception:
        pass
    _client = None
    _db = None


def _ensure_connection() -> bool:
    global _client, _db, _connection_error
    if _client is not None:
        try:
            if _client.is_connected():
                return True
        except Exception:
            pass
        _drop_connection()
    if not _connection_params:
        return False
    try:
        _connect()
        _connection_error = None
        return True
    except (MySQLError, OSError, ValueError, UnicodeError) as exc:
        _drop_connection()
        _connection_error = exc
        print(f"MySQL reconnect failed: {exc}")
        return False


def get_db():
    if not _ensure_connection():
        raise RuntimeError("Database not initialized. Call init_db first.")
    return _db


def col(name: str) -> Collection:
    return Collection(name)


def _ensure_schema() -> None:
    # Caller must hold _db_lock when needed
    if not _ensure_connection():
        return
    cursor = _client.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS generic_documents (
                collection_name VARCHAR(64) NOT NULL,
                document_id VARCHAR(128) NOT NULL,
                data LONGTEXT NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (collection_name, document_id)
            )
            """
        )
        _client.commit()
    finally:
        cursor.close()


def _parse_mysql_uri(uri: str) -> dict[str, Any]:
    """Parse mysql://user:password@host:port/db (password may contain @)."""
    from urllib.parse import unquote

    cleaned = (uri or "").strip()
    defaults = {"host": "localhost", "port": 3306, "user": "root", "password": "", "database": DEFAULT_DB_NAME}
    if "://" not in cleaned:
        return defaults
    rest = cleaned.split("://", 1)[1]
    if "/" in rest:
        auth_host, database = rest.split("/", 1)
        database = database.split("?")[0] or DEFAULT_DB_NAME
    else:
        auth_host, database = rest, DEFAULT_DB_NAME

    if "@" in auth_host:
        auth, hostport = auth_host.rsplit("@", 1)
        if ":" in auth:
            user, password = auth.split(":", 1)
        else:
            user, password = auth, ""
        user, password = unquote(user), unquote(password)
    else:
        user, password, hostport = "root", "", auth_host

    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s) if port_s.isdigit() else 3306
    else:
        host, port = hostport or "localhost", 3306

    return {
        "host": host or "localhost",
        "port": port,
        "user": user or "root",
        "password": password,
        "database": database or DEFAULT_DB_NAME,
    }


def _matches_filter(doc: dict, filter_: dict | None) -> bool:
    if not filter_:
        return True
    for key, expected in filter_.items():
        if isinstance(expected, dict):
            if "$in" in expected:
                if doc.get(key) not in expected["$in"]:
                    return False
            elif "$regex" in expected:
                pattern = expected.get("$regex", "")
                flags = expected.get("$options", "")
                value = str(doc.get(key, ""))
                if "i" in flags:
                    value = value.lower()
                    pattern = pattern.lower()
                if pattern not in value:
                    return False
            else:
                return False
        else:
            if doc.get(key) != expected:
                return False
    return True


def _sort_value(value: Any):
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return ""
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
