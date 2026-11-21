"""Schema.org Recipe JSON-LD generation and SSR helpers for HomeView Safari."""

from __future__ import annotations

import html
import json
import re
from typing import Any

_ISO_RE = re.compile(r"^P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$", re.IGNORECASE)
_NUM_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b",
    re.IGNORECASE,
)


def parse_iso_duration(text: str) -> str:
    """Convert human-readable Paprika durations (e.g. '1 hr 20 mins') to ISO 8601 ('PT1H20M')."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if _ISO_RE.match(cleaned) and cleaned.upper() not in ("P", "PT"):
        return cleaned.upper()

    days = 0
    hours = 0
    minutes = 0
    seconds = 0
    matched = False

    for num_str, unit in _NUM_UNIT_RE.findall(cleaned):
        matched = True
        val = float(num_str)
        u = unit.lower()
        if u.startswith("d"):
            days += int(val)
            hours += int(round((val - int(val)) * 24))
        elif u.startswith("h"):
            hours += int(val)
            minutes += int(round((val - int(val)) * 60))
        elif u.startswith("m"):
            minutes += int(val)
            seconds += int(round((val - int(val)) * 60))
        elif u.startswith("s"):
            seconds += int(round(val))

    if not matched:
        return ""

    if seconds >= 60:
        minutes += seconds // 60
        seconds = seconds % 60
    if minutes >= 60:
        hours += minutes // 60
        minutes = minutes % 60

    date_part = f"{days}D" if days else ""
    time_parts = []
    if hours:
        time_parts.append(f"{hours}H")
    if minutes:
        time_parts.append(f"{minutes}M")
    if seconds:
        time_parts.append(f"{seconds}S")
    time_part = f"T{''.join(time_parts)}" if time_parts else ""

    if not date_part and not time_part:
        return ""
    return f"P{date_part}{time_part}"


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.endswith(":") and len(s) <= 64:
        return True
    if re.fullmatch(r"[A-Z0-9\s,&'/-]{4,48}", s) and re.search(r"[A-Z]", s):
        return True
    return False


def build_recipe_jsonld(recipe: dict[str, Any], base_url: str = "") -> dict[str, Any]:
    """Build a Schema.org Recipe JSON-LD object for Safari's Cooking Mode."""
    data: dict[str, Any] = {
        "@context": "https://schema.org/",
        "@type": "Recipe",
        "name": recipe.get("name") or "Untitled Recipe",
    }

    photo_url = recipe.get("photo_url") or ""
    image_url = recipe.get("image_url") or ""
    if photo_url:
        data["image"] = [f"{base_url.rstrip('/')}{photo_url}" if base_url else photo_url]
    elif image_url.startswith(("http://", "https://")):
        data["image"] = [image_url]

    description = (recipe.get("description") or "").strip()
    if description:
        data["description"] = description
    elif recipe.get("notes"):
        data["description"] = recipe["notes"].strip().splitlines()[0][:240]

    if recipe.get("source"):
        data["author"] = {
            "@type": "Organization",
            "name": recipe["source"],
        }

    for field, schema_key in (
        ("prep_time", "prepTime"),
        ("cook_time", "cookTime"),
        ("total_time", "totalTime"),
    ):
        iso = parse_iso_duration(recipe.get(field, ""))
        if iso:
            data[schema_key] = iso

    if recipe.get("servings"):
        data["recipeYield"] = recipe["servings"]

    categories = recipe.get("categories") or []
    if categories:
        data["recipeCategory"] = categories[0] if len(categories) == 1 else categories

    ingredients = [
        line.strip()
        for line in (recipe.get("ingredients") or "").splitlines()
        if line.strip() and not _is_heading(line)
    ]
    if ingredients:
        data["recipeIngredient"] = ingredients

    steps = []
    for block in re.split(r"\n+", (recipe.get("directions") or "").strip()):
        cleaned = block.strip()
        if not cleaned or _is_heading(cleaned):
            continue
        cleaned = re.sub(r"^\d+[\.\)]\s+", "", cleaned)
        steps.append({"@type": "HowToStep", "text": cleaned})
    if steps:
        data["recipeInstructions"] = steps

    rating = recipe.get("rating") or 0
    if isinstance(rating, int) and 1 <= rating <= 5:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": rating,
            "bestRating": 5,
            "worstRating": 1,
            "ratingCount": 1,
        }

    return data


def _safe_script_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def render_recipe_html(
    template_html: str, recipe: dict[str, Any], base_url: str = ""
) -> bytes:
    """Inject Schema.org Recipe JSON-LD, page title, and initial recipe data into index.html."""
    title = html.escape(recipe.get("name") or "Paprika Recipe")
    jsonld = _safe_script_json(build_recipe_jsonld(recipe, base_url=base_url))
    initial_json = _safe_script_json(recipe)

    head_injection = (
        f"<title>{title} — Paprika</title>\n"
        f'  <script type="application/ld+json">{jsonld}</script>'
    )
    rendered = template_html.replace("<title>Paprika Recipes</title>", head_injection, 1)

    body_injection = (
        f'<script id="initial-recipe" type="application/json">{initial_json}</script>\n'
        f"</body>"
    )
    rendered = rendered.replace("</body>", body_injection, 1)
    return rendered.encode("utf-8")
