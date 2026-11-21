"""Parser for Paprika 3 export files (.paprikarecipes and .paprikarecipe)."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

GZIP_MAGIC = b"\x1f\x8b"


def _detect_image_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _decode_base64_image(raw: Any) -> bytes | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]
    try:
        return base64.b64decode(cleaned, validate=False)
    except Exception:
        return None


def _normalize_categories(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = raw.split(",")
    else:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        val = item.strip()
        if val and val.lower() not in seen:
            seen.add(val.lower())
            result.append(val)
    return result


def _normalize_rating(raw: Any) -> int:
    try:
        val = int(round(float(raw)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, val))


def _normalize_str(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def normalize_recipe(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw Paprika recipe JSON object into our normalized structure."""
    if raw.get("in_trash"):
        return None

    name = _normalize_str(raw.get("name")) or "Untitled Recipe"
    created = _normalize_str(raw.get("created"))
    uid = _normalize_str(raw.get("uid"))
    if not uid:
        uid = hashlib.sha256(f"{name}|{created}".encode("utf-8")).hexdigest()[:32]

    photo_bytes = _decode_base64_image(raw.get("photo_data"))
    if not photo_bytes and isinstance(raw.get("photos"), list):
        for photo_entry in raw["photos"]:
            if isinstance(photo_entry, dict):
                photo_bytes = _decode_base64_image(photo_entry.get("data"))
                if photo_bytes:
                    break

    photo_ext = _detect_image_ext(photo_bytes) if photo_bytes else ""

    return {
        "uid": uid,
        "name": name,
        "ingredients": (raw.get("ingredients") or "").replace("\r\n", "\n").strip(),
        "directions": (raw.get("directions") or "").replace("\r\n", "\n").strip(),
        "description": (raw.get("description") or "").replace("\r\n", "\n").strip(),
        "notes": (raw.get("notes") or "").replace("\r\n", "\n").strip(),
        "nutritional_info": (raw.get("nutritional_info") or "").replace("\r\n", "\n").strip(),
        "prep_time": _normalize_str(raw.get("prep_time")),
        "cook_time": _normalize_str(raw.get("cook_time")),
        "total_time": _normalize_str(raw.get("total_time")),
        "servings": _normalize_str(raw.get("servings")),
        "difficulty": _normalize_str(raw.get("difficulty")),
        "rating": _normalize_rating(raw.get("rating")),
        "source": _normalize_str(raw.get("source")),
        "source_url": _normalize_str(raw.get("source_url")),
        "categories": _normalize_categories(raw.get("categories")),
        "created": created,
        "image_url": _normalize_str(raw.get("image_url")),
        "photo_bytes": photo_bytes,
        "photo_ext": photo_ext,
    }


def _decode_recipe_bytes(payload: bytes) -> Any:
    if payload.startswith(GZIP_MAGIC):
        payload = gzip.decompress(payload)
    return json.loads(payload.decode("utf-8-sig"))


def parse_paprika_file(file_path: Path) -> Iterator[dict[str, Any]]:
    """Yield normalized recipe dicts from a .paprikarecipes ZIP or single .paprikarecipe/.json file."""
    if zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                basename = Path(name).name
                if name.startswith("__MACOSX/") or basename.startswith("."):
                    continue
                lower = basename.lower()
                if not (lower.endswith(".paprikarecipe") or lower.endswith(".json")):
                    continue
                try:
                    data = zf.read(info)
                    parsed = _decode_recipe_bytes(data)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    normalized = normalize_recipe(parsed)
                    if normalized is not None:
                        yield normalized
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            normalized = normalize_recipe(item)
                            if normalized is not None:
                                yield normalized
        return

    raw_bytes = file_path.read_bytes()
    parsed = _decode_recipe_bytes(raw_bytes)
    if isinstance(parsed, dict):
        normalized = normalize_recipe(parsed)
        if normalized is not None:
            yield normalized
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                normalized = normalize_recipe(item)
                if normalized is not None:
                    yield normalized
    else:
        raise ValueError("Unsupported file format: expected Paprika export or JSON object")
