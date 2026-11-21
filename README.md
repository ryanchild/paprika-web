# Paprika Web

A lightweight, self-hosted web viewer for [Paprika Recipe Manager](https://www.paprikaapp.com/) exports, designed to look and work great on **HomeView Safari**, iPadOS/iOS Safari, and desktop browsers.

## Features

- **Import Paprika Exports**: Drag-and-drop or upload `.paprikarecipes` (ZIP archive) or individual `.paprikarecipe` files straight from Safari or Files/iCloud Drive. Supports **Merge** and **Replace all** modes.
- **Fast, Persistent Library**: Recipes are stored in SQLite (`/data/paprika.db`) with extracted photos cached on disk (`/data/photos`) so large libraries load instantaneously.
- **Kitchen-Ready Reading View**:
  - Instant search across titles, ingredients, categories, sources, and notes
  - Category filter pills and sorting (Name, Recently Added, Highest Rated)
  - Interactive ingredient check-off and tap-to-highlight direction steps
  - Serving scaler (`½×`, `1×`, `2×`, `3×`)
  - Font size controls (`A-` / `A+`), Screen Wake Lock (`Keep Awake`), Light/Dark mode, and Print view
- **Zero External Dependencies**: Pure Python 3.12 standard library server + vanilla HTML/CSS/JS frontend (~50 MB multi-arch Docker image for `linux/amd64` and `linux/arm64`).

## Synology Container Manager Setup

### Option 1: Project (`docker-compose.yml`) — Recommended

1. Open **Container Manager** on your Synology NAS.
2. Go to **Project** &rarr; **Create**.
3. Set a project name (e.g., `paprika-web`) and path (e.g., `/docker/paprika-web`).
4. Choose **Create docker-compose.yml** and paste:

```yaml
services:
  paprika-web:
    image: ghcr.io/ryanchild/paprika-web:latest
    container_name: paprika-web
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - PORT=8080
      - DATA_DIR=/data
    volumes:
      - ./data:/data
```

5. Click **Next** &rarr; **Done**. Open `http://<your-nas-ip>:8080` in Safari!

### Option 2: Direct Image Pull

1. In **Container Manager** &rarr; **Image** &rarr; **Add** &rarr; **Add From URL**, enter:
   ```
   ghcr.io/ryanchild/paprika-web:latest
   ```
2. Create a container from the image with:
   - **Port**: `8080` &rarr; `8080` (TCP)
   - **Volume**: `/docker/paprika-web/data` &rarr; `/data` (Read/Write)

## Exporting from Paprika 3

1. In Paprika 3, go to **Settings** &rarr; **Export Recipes**.
2. Choose **Paprika Recipe Format** (`.paprikarecipes`).
3. Open Paprika Web in Safari, click **Import**, and select the exported file.

## Local Development

```bash
python3 -m app.server
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Configuration

| Environment Variable | Default | Description |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Interface to bind |
| `PORT` | `8080` | HTTP port |
| `DATA_DIR` | `/data` | Directory for SQLite database and extracted photos |
| `MAX_UPLOAD_MB` | `500` | Maximum `.paprikarecipes` upload size in MB |
