"""HTTP server and REST API for Paprika Web."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.db import RecipeStore
from app.parser import parse_paprika_file

STATIC_DIR = Path(__file__).resolve().parent / "static"
CHUNK_SIZE = 65536


def _extract_multipart_file(raw_body: bytes, content_type: str) -> bytes:
    """Extract the first file part from a multipart/form-data payload."""
    header_bytes = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode(
        "utf-8"
    )
    msg = BytesParser(policy=email_policy).parsebytes(header_bytes + raw_body)
    if msg.is_multipart():
        for part in msg.iter_parts():
            if part.get_filename() or part.get_content_disposition() == "form-data":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload
    raise ValueError("No file found in multipart upload")


def make_handler(store: RecipeStore, max_upload_bytes: int):
    class PaprikaHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            # Concise structured log to stdout
            print(f"[paprika-web] {self.address_string()} - {format % args}", flush=True)

        def _send_bytes(
            self,
            data: bytes,
            content_type: str,
            status: int = HTTPStatus.OK,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                if extra_headers:
                    for key, value in extra_headers.items():
                        self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _send_json(
            self,
            payload: Any,
            status: int = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(
                body,
                "application/json; charset=utf-8",
                status=status,
                extra_headers={"Cache-Control": "no-store"},
            )

        def _serve_file(
            self,
            path: Path,
            cache_control: str = "no-cache",
        ) -> None:
            if not path.is_file():
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            mime, _ = mimetypes.guess_type(str(path))
            if not mime:
                mime = "application/octet-stream"
            if mime.startswith("text/") or mime in (
                "application/javascript",
                "image/svg+xml",
            ):
                mime = f"{mime}; charset=utf-8"

            stat = path.stat()
            etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
            if self.headers.get("If-None-Match") == etag:
                try:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", cache_control)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return

            data = path.read_bytes()
            self._send_bytes(
                data,
                mime,
                status=HTTPStatus.OK,
                extra_headers={
                    "Cache-Control": cache_control,
                    "ETag": etag,
                },
            )

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            if path == "/api/health":
                self._send_json({"status": "ok", "recipes": store.count_recipes()})
                return

            if path == "/api/categories":
                self._send_json(store.list_categories())
                return

            if path == "/api/recipes":
                q = query.get("q", [""])[0]
                category = query.get("category", [""])[0]
                sort = query.get("sort", ["name"])[0]
                try:
                    min_rating = int(query.get("min_rating", ["0"])[0])
                except ValueError:
                    min_rating = 0
                recipes = store.list_recipes(
                    q=q, category=category, min_rating=min_rating, sort=sort
                )
                self._send_json({"recipes": recipes, "count": len(recipes)})
                return

            if path.startswith("/api/recipes/"):
                uid = path[len("/api/recipes/") :]
                recipe = store.get_recipe(uid)
                if not recipe:
                    self._send_json({"error": "Recipe not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json(recipe)
                return

            if path.startswith("/api/photos/"):
                filename = path[len("/api/photos/") :]
                photo_path = store.get_photo_path(filename)
                if not photo_path:
                    self._send_json({"error": "Photo not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._serve_file(
                    photo_path,
                    cache_control="public, max-age=31536000, immutable",
                )
                return

            # Static assets
            if path in ("/", "/index.html"):
                self._serve_file(STATIC_DIR / "index.html", cache_control="no-cache")
                return

            rel = path.lstrip("/")
            if rel and ".." not in rel and "/" not in rel:
                candidate = STATIC_DIR / rel
                if candidate.is_file():
                    self._serve_file(candidate, cache_control="no-cache")
                    return

            # SPA fallback for non-API routes
            if not path.startswith("/api/"):
                self._serve_file(STATIC_DIR / "index.html", cache_control="no-cache")
                return

            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)

            if path != "/api/import":
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return

            content_length_raw = self.headers.get("Content-Length")
            if not content_length_raw:
                self._send_json(
                    {"error": "Missing Content-Length header"},
                    HTTPStatus.LENGTH_REQUIRED,
                )
                return

            try:
                content_length = int(content_length_raw)
            except ValueError:
                self._send_json(
                    {"error": "Invalid Content-Length header"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

            if content_length <= 0:
                self._send_json(
                    {"error": "Uploaded file is empty"}, HTTPStatus.BAD_REQUEST
                )
                return

            if content_length > max_upload_bytes:
                self._send_json(
                    {
                        "error": f"File exceeds maximum size of {max_upload_bytes // (1024 * 1024)} MB"
                    },
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return

            mode = query.get("mode", ["merge"])[0].lower()
            replace = mode == "replace"
            content_type = self.headers.get("Content-Type", "")

            tmp_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix="paprika_upload_", suffix=".bin", delete=False
                ) as tmp:
                    tmp_path = Path(tmp.name)
                    if content_type.lower().startswith("multipart/form-data"):
                        raw_body = self.rfile.read(content_length)
                        file_bytes = _extract_multipart_file(raw_body, content_type)
                        tmp.write(file_bytes)
                    else:
                        remaining = content_length
                        while remaining > 0:
                            chunk = self.rfile.read(min(CHUNK_SIZE, remaining))
                            if not chunk:
                                break
                            tmp.write(chunk)
                            remaining -= len(chunk)

                recipes = list(parse_paprika_file(tmp_path))
                if not recipes:
                    self._send_json(
                        {
                            "error": "No valid Paprika recipes found in the uploaded file."
                        },
                        HTTPStatus.BAD_REQUEST,
                    )
                    return

                stats = store.import_recipes(recipes, replace=replace)
                self._send_json(
                    {
                        "status": "ok",
                        "mode": "replace" if replace else "merge",
                        "imported": len(recipes),
                        **stats,
                    }
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json(
                    {"error": f"Failed to import Paprika export: {exc}"},
                    HTTPStatus.BAD_REQUEST,
                )
            finally:
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if path == "/api/recipes":
                deleted = store.clear_all()
                self._send_json({"status": "ok", "deleted": deleted})
                return

            if path.startswith("/api/recipes/"):
                uid = path[len("/api/recipes/") :]
                if store.delete_recipe(uid):
                    self._send_json({"status": "ok", "uid": uid})
                else:
                    self._send_json({"error": "Recipe not found"}, HTTPStatus.NOT_FOUND)
                return

            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    return PaprikaHandler


def create_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    data_dir: Path | None = None,
    max_upload_mb: int = 500,
) -> ThreadingHTTPServer:
    if data_dir is None:
        env_dir = os.environ.get("DATA_DIR")
        if env_dir:
            data_dir = Path(env_dir)
        elif Path("/data").exists():
            data_dir = Path("/data")
        else:
            data_dir = Path.cwd() / "data"

    store = RecipeStore(data_dir)
    handler_cls = make_handler(store, max_upload_bytes=max_upload_mb * 1024 * 1024)
    server = ThreadingHTTPServer((host, port), handler_cls)
    server.daemon_threads = True
    return server


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "500"))
    server = create_server(host=host, port=port, max_upload_mb=max_upload_mb)
    print(f"[paprika-web] Listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
