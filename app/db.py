"""SQLite persistence and photo storage for Paprika Web."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recipes (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ingredients TEXT NOT NULL DEFAULT '',
    directions TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    nutritional_info TEXT NOT NULL DEFAULT '',
    prep_time TEXT NOT NULL DEFAULT '',
    cook_time TEXT NOT NULL DEFAULT '',
    total_time TEXT NOT NULL DEFAULT '',
    servings TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    rating INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    categories_json TEXT NOT NULL DEFAULT '[]',
    created TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT '',
    photo_filename TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipes_name ON recipes(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_recipes_rating ON recipes(rating DESC);
CREATE INDEX IF NOT EXISTS idx_recipes_created ON recipes(created DESC);
"""


class RecipeStore:
    """Thread-safe SQLite recipe store with on-disk photo files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.photos_dir = self.data_dir / "photos"
        self.db_path = self.data_dir / "paprika.db"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _save_photo(self, uid: str, photo_bytes: bytes | None, ext: str) -> str:
        if not photo_bytes:
            return ""
        uid_hash = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:16]
        content_hash = hashlib.sha256(photo_bytes).hexdigest()[:12]
        safe_ext = ext if ext in {".jpg", ".png", ".gif", ".webp"} else ".jpg"
        filename = f"{uid_hash}_{content_hash}{safe_ext}"
        dest = self.photos_dir / filename
        if not dest.exists():
            dest.write_bytes(photo_bytes)
        return filename

    def _cleanup_orphan_photos(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT photo_filename FROM recipes WHERE photo_filename != ''"
        ).fetchall()
        active = {row["photo_filename"] for row in rows}
        for path in self.photos_dir.iterdir():
            if path.is_file() and path.name not in active:
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
        photo_filename = row["photo_filename"]
        return {
            "uid": row["uid"],
            "name": row["name"],
            "prep_time": row["prep_time"],
            "cook_time": row["cook_time"],
            "total_time": row["total_time"],
            "servings": row["servings"],
            "difficulty": row["difficulty"],
            "rating": row["rating"],
            "source": row["source"],
            "categories": json.loads(row["categories_json"] or "[]"),
            "created": row["created"],
            "photo_url": f"/api/photos/{photo_filename}" if photo_filename else "",
            "image_url": row["image_url"],
        }

    @staticmethod
    def _row_to_detail(row: sqlite3.Row) -> dict[str, Any]:
        data = RecipeStore._row_to_summary(row)
        data.update(
            {
                "ingredients": row["ingredients"],
                "directions": row["directions"],
                "description": row["description"],
                "notes": row["notes"],
                "nutritional_info": row["nutritional_info"],
                "source_url": row["source_url"],
                "imported_at": row["imported_at"],
            }
        )
        return data

    def count_recipes(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM recipes").fetchone()
            return int(row["cnt"]) if row else 0

    def list_recipes(
        self,
        q: str = "",
        category: str = "",
        min_rating: int = 0,
        sort: str = "name",
    ) -> list[dict[str, Any]]:
        order_map = {
            "name": "name COLLATE NOCASE ASC",
            "created": "created DESC, name COLLATE NOCASE ASC",
            "rating": "rating DESC, name COLLATE NOCASE ASC",
        }
        order_by = order_map.get(sort, order_map["name"])

        clauses: list[str] = []
        params: list[Any] = []

        if q.strip():
            # Split query into tokens so multi-word search matches across fields
            for token in q.strip().split():
                like = f"%{token}%"
                clauses.append(
                    "(name LIKE ? OR ingredients LIKE ? OR categories_json LIKE ? OR source LIKE ? OR notes LIKE ? OR description LIKE ?)"
                )
                params.extend([like, like, like, like, like, like])

        if min_rating > 0:
            clauses.append("rating >= ?")
            params.append(min_rating)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT uid, name, prep_time, cook_time, total_time, servings,
                   difficulty, rating, source, categories_json, created,
                   photo_filename, image_url
            FROM recipes
            {where_sql}
            ORDER BY {order_by}
        """

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = [self._row_to_summary(r) for r in rows]
        if category.strip():
            target = category.strip().lower()
            if target == "__uncategorized__":
                results = [r for r in results if not r["categories"]]
            else:
                results = [
                    r
                    for r in results
                    if any(c.lower() == target for c in r["categories"])
                ]
        return results

    def get_recipe(self, uid: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM recipes WHERE uid = ?", (uid,)
            ).fetchone()
        return self._row_to_detail(row) if row else None

    def list_categories(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT categories_json FROM recipes").fetchall()

        counts: dict[str, int] = {}
        display_names: dict[str, str] = {}
        uncategorized = 0

        for row in rows:
            cats = json.loads(row["categories_json"] or "[]")
            if not cats:
                uncategorized += 1
                continue
            for cat in cats:
                key = cat.lower()
                if key not in display_names:
                    display_names[key] = cat
                counts[key] = counts.get(key, 0) + 1

        categories = [
            {"name": display_names[k], "count": counts[k]}
            for k in sorted(display_names, key=lambda s: display_names[s].lower())
        ]
        return {
            "total": len(rows),
            "uncategorized": uncategorized,
            "categories": categories,
        }

    def import_recipes(
        self, recipes: Iterable[dict[str, Any]], replace: bool = False
    ) -> dict[str, int]:
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        updated = 0

        with self._lock, self._connect() as conn:
            if replace:
                conn.execute("DELETE FROM recipes")
                existing_uids: set[str] = set()
            else:
                existing_rows = conn.execute("SELECT uid FROM recipes").fetchall()
                existing_uids = {row["uid"] for row in existing_rows}

            for recipe in recipes:
                uid = recipe["uid"]
                photo_filename = self._save_photo(
                    uid, recipe.get("photo_bytes"), recipe.get("photo_ext", ".jpg")
                )
                if not photo_filename and uid in existing_uids:
                    prev = conn.execute(
                        "SELECT photo_filename FROM recipes WHERE uid = ?", (uid,)
                    ).fetchone()
                    if prev:
                        photo_filename = prev["photo_filename"]

                if uid in existing_uids:
                    updated += 1
                else:
                    added += 1
                    existing_uids.add(uid)

                conn.execute(
                    """
                    INSERT INTO recipes (
                        uid, name, ingredients, directions, description, notes,
                        nutritional_info, prep_time, cook_time, total_time,
                        servings, difficulty, rating, source, source_url,
                        categories_json, created, image_url, photo_filename,
                        imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uid) DO UPDATE SET
                        name = excluded.name,
                        ingredients = excluded.ingredients,
                        directions = excluded.directions,
                        description = excluded.description,
                        notes = excluded.notes,
                        nutritional_info = excluded.nutritional_info,
                        prep_time = excluded.prep_time,
                        cook_time = excluded.cook_time,
                        total_time = excluded.total_time,
                        servings = excluded.servings,
                        difficulty = excluded.difficulty,
                        rating = excluded.rating,
                        source = excluded.source,
                        source_url = excluded.source_url,
                        categories_json = excluded.categories_json,
                        created = excluded.created,
                        image_url = excluded.image_url,
                        photo_filename = excluded.photo_filename,
                        imported_at = excluded.imported_at
                    """,
                    (
                        uid,
                        recipe["name"],
                        recipe["ingredients"],
                        recipe["directions"],
                        recipe["description"],
                        recipe["notes"],
                        recipe["nutritional_info"],
                        recipe["prep_time"],
                        recipe["cook_time"],
                        recipe["total_time"],
                        recipe["servings"],
                        recipe["difficulty"],
                        recipe["rating"],
                        recipe["source"],
                        recipe["source_url"],
                        json.dumps(recipe["categories"], ensure_ascii=False),
                        recipe["created"],
                        recipe["image_url"],
                        photo_filename,
                        now,
                    ),
                )

            self._cleanup_orphan_photos(conn)
            total_row = conn.execute("SELECT COUNT(*) AS cnt FROM recipes").fetchone()
            total = int(total_row["cnt"]) if total_row else 0

        return {"added": added, "updated": updated, "total": total}

    def delete_recipe(self, uid: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM recipes WHERE uid = ?", (uid,))
            deleted = cursor.rowcount > 0
            if deleted:
                self._cleanup_orphan_photos(conn)
        return deleted

    def clear_all(self) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM recipes")
            count = cursor.rowcount
            self._cleanup_orphan_photos(conn)
        return count

    def get_photo_path(self, filename: str) -> Path | None:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return None
        path = (self.photos_dir / filename).resolve()
        if path.parent != self.photos_dir.resolve() or not path.is_file():
            return None
        return path
