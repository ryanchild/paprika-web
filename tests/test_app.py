"""Unit and integration tests for Paprika Web."""

from __future__ import annotations

import base64
import gzip
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from app.db import RecipeStore
from app.parser import parse_paprika_file
from app.server import create_server

# 1x1 transparent PNG
SAMPLE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _make_paprika_zip(recipes: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("__MACOSX/._ignore.paprikarecipe", b"junk")
        for idx, rec in enumerate(recipes):
            gz = gzip.compress(json.dumps(rec).encode("utf-8"))
            zf.writestr(f"Recipe_{idx}.paprikarecipe", gz)
    return buf.getvalue()


class PaprikaWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmpdir.name) / "data"
        self.server = create_server(host="127.0.0.1", port=0, data_dir=self.data_dir)
        self.port = self.server.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmpdir.cleanup()

    def _req(
        self,
        path: str,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read(), dict(err.headers)

    def test_health_and_static_index(self) -> None:
        status, body, _ = self._req("/api/health")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload, {"status": "ok", "recipes": 0})

        status, html, headers = self._req("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"Paprika", html)

    def test_import_zip_and_render_api(self) -> None:
        zip_bytes = _make_paprika_zip(
            [
                {
                    "uid": "uid-pasta",
                    "name": "Garlic Butter Pasta",
                    "ingredients": "1 lb spaghetti\n4 tbsp butter\n4 cloves garlic",
                    "directions": "Boil pasta.\n\nSaute garlic in butter and toss.",
                    "prep_time": "10 mins",
                    "cook_time": "15 mins",
                    "servings": "4",
                    "rating": 5,
                    "categories": ["Dinner", "Italian"],
                    "source": "Kitchen Notes",
                    "source_url": "https://example.com/pasta",
                    "photo_data": base64.b64encode(SAMPLE_PNG).decode("ascii"),
                },
                {
                    "uid": "uid-salad",
                    "name": "Caesar Salad",
                    "ingredients": "1 head romaine\nParmesan",
                    "directions": "Chop and toss.",
                    "rating": 4,
                    "categories": ["Lunch"],
                },
                {
                    "uid": "uid-trashed",
                    "name": "Deleted Soup",
                    "in_trash": True,
                },
            ]
        )

        status, body, _ = self._req(
            "/api/import?mode=merge",
            method="POST",
            data=zip_bytes,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(status, 200)
        res = json.loads(body)
        self.assertEqual(res["added"], 2)
        self.assertEqual(res["updated"], 0)
        self.assertEqual(res["total"], 2)

        # List & filter
        status, body, _ = self._req("/api/recipes?q=garlic")
        self.assertEqual(status, 200)
        listed = json.loads(body)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["recipes"][0]["uid"], "uid-pasta")
        photo_url = listed["recipes"][0]["photo_url"]
        self.assertTrue(photo_url.startswith("/api/photos/"))
        self.assertTrue(photo_url.endswith(".png"))

        # Serve photo
        status, photo_body, headers = self._req(photo_url)
        self.assertEqual(status, 200)
        self.assertEqual(photo_body, SAMPLE_PNG)
        self.assertIn("image/png", headers.get("Content-Type", ""))

        # Detail endpoint
        status, body, _ = self._req("/api/recipes/uid-pasta")
        self.assertEqual(status, 200)
        detail = json.loads(body)
        self.assertIn("4 cloves garlic", detail["ingredients"])
        self.assertEqual(detail["rating"], 5)

        # Server-rendered recipe page with Schema.org JSON-LD for HomeView Safari
        status, page_html, headers = self._req("/recipe/uid-pasta")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html_text = page_html.decode("utf-8")
        self.assertIn('<script type="application/ld+json">', html_text)
        self.assertIn('<script id="initial-recipe" type="application/json">', html_text)
        ld_start = html_text.index('<script type="application/ld+json">') + len(
            '<script type="application/ld+json">'
        )
        ld_end = html_text.index("</script>", ld_start)
        schema = json.loads(html_text[ld_start:ld_end])
        self.assertEqual(schema["@type"], "Recipe")
        self.assertEqual(schema["name"], "Garlic Butter Pasta")
        self.assertEqual(schema["prepTime"], "PT10M")
        self.assertEqual(schema["cookTime"], "PT15M")
        self.assertEqual(len(schema["recipeIngredient"]), 3)
        self.assertEqual(len(schema["recipeInstructions"]), 2)
        self.assertEqual(schema["recipeInstructions"][0]["@type"], "HowToStep")
        self.assertTrue(schema["image"][0].startswith("http://127.0.0.1:"))

        # Categories endpoint
        status, body, _ = self._req("/api/categories")
        self.assertEqual(status, 200)
        cats = json.loads(body)
        self.assertEqual(cats["total"], 2)
        cat_names = [c["name"] for c in cats["categories"]]
        self.assertEqual(cat_names, ["Dinner", "Italian", "Lunch"])

        # Replace mode removes previous recipes
        single_recipe = gzip.compress(
            json.dumps(
                {
                    "uid": "uid-tacos",
                    "name": "Street Tacos",
                    "ingredients": "Corn tortillas",
                    "directions": "Warm and fill.",
                    "categories": ["Dinner"],
                }
            ).encode("utf-8")
        )
        status, body, _ = self._req(
            "/api/import?mode=replace",
            method="POST",
            data=single_recipe,
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(status, 200)
        res = json.loads(body)
        self.assertEqual(res["total"], 1)

        # Old recipe should be gone
        status, _, _ = self._req("/api/recipes/uid-pasta")
        self.assertEqual(status, 404)

    def test_delete_single_and_clear_all(self) -> None:
        zip_bytes = _make_paprika_zip(
            [
                {"uid": "r1", "name": "One"},
                {"uid": "r2", "name": "Two"},
            ]
        )
        self._req("/api/import", method="POST", data=zip_bytes)

        status, _, _ = self._req("/api/recipes/r1", method="DELETE")
        self.assertEqual(status, 200)

        status, body, _ = self._req("/api/health")
        self.assertEqual(json.loads(body)["recipes"], 1)

        status, body, _ = self._req("/api/recipes", method="DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["deleted"], 1)

        status, body, _ = self._req("/api/health")
        self.assertEqual(json.loads(body)["recipes"], 0)


if __name__ == "__main__":
    unittest.main()
