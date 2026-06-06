# Memoria

A local-first photo and video library manager for Windows, built for power users managing large personal collections (30,000+ photos, 2,000+ videos).

All processing happens on-device — no cloud AI, no telemetry, no subscription.

![Memoria Screenshot](docs/screenshot.png)

---

## Features

- **Smart indexing** — recursively scans watched folders, extracts EXIF/video metadata, detects duplicates via perceptual hashing
- **Face recognition** — detects and clusters faces using DeepFace (local models only); user names clusters to build a personal people index
- **Reverse geocoding** — converts GPS coordinates to human-readable location labels, fully offline
- **Duplicate detection** — perceptual hashing flags near-identical images for review
- **Modern dark UI** — PyQt6 card grid with adjustable thumbnail size, sidebar filters, and a metadata detail panel
- **Local backup** — one-click backup of the database and face encodings to any destination (external drive, NAS, network share)
- **No cloud dependency** — Google Drive, iCloud, and similar services are not required; sync via whatever client you already use

---

## Tech Stack

| Layer | Technology |
|---|---|
| UI | PyQt6 |
| Database | SQLite via SQLAlchemy ORM |
| Face recognition | DeepFace (ArcFace model, local inference) |
| EXIF parsing | Pillow + exifread |
| Duplicate detection | imagehash (perceptual hashing) |
| Video metadata | ffprobe via ffmpeg-python |
| Reverse geocoding | reverse_geocoder (offline dataset) |
| Clustering | Pure numpy (no compiled extensions) |

---

## Architecture

```
Memoria/
├── memoria/
│   ├── database/       # SQLAlchemy models + session management
│   ├── indexer/        # Folder scanner, EXIF, video, hashing, geocoding
│   ├── faces/          # DeepFace encoding + numpy clustering pipeline
│   ├── ui/             # PyQt6 main window, grid view, detail panel
│   └── sync/           # Local backup / restore
├── main.py             # Entry point (UI + CLI)
└── requirements.txt
```

All persistent data (database, face encodings, thumbnails, logs, AI models) is stored in `%APPDATA%\Memoria\` — completely separate from your photo library. **Original files are never moved or modified.**

---

## Prerequisites

- Python 3.13
- Visual Studio 2022 (Desktop development with C++ workload) — required for native pip packages
- ffmpeg on PATH — `winget install ffmpeg`

---

## Installation

```powershell
git clone https://github.com/yourusername/Memoria.git
cd Memoria
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Usage

**Launch the UI:**
```powershell
python main.py
```

**CLI commands:**
```powershell
# Add a folder to watch
python main.py add-folder "C:\path\to\photos"

# Index all watched folders (extract metadata, detect duplicates)
python main.py index

# Scan photos for faces (downloads AI models ~500MB on first run)
python main.py scan-faces

# Cluster detected faces ready for naming in the UI
python main.py cluster-faces
```

---

## Design Decisions

**Why local-only AI?**
Privacy. Face recognition data and photo metadata are sensitive. No embeddings, GPS coordinates, or image data ever leave the machine.

**Why SQLite?**
Simplicity and portability. The entire index is a single file that can be backed up, versioned, or transferred to another machine in seconds.

**Why pure-numpy clustering?**
Windows Code Integrity policies (common in enterprise environments) block unsigned compiled extensions. The clustering algorithm is implemented entirely in numpy, which is code-signed and universally trusted.

**Why not move/rename files during indexing?**
Non-destructive by default. The indexer records the current filepath and never touches originals unless the user explicitly triggers a rename action.

---

## Roadmap

- [x] Phase 1 — Project scaffold and database schema
- [x] Phase 2 — Indexing engine (EXIF, video, hashing, geocoding)
- [x] Phase 3 — Face recognition pipeline
- [x] Phase 4a — Main window and photo grid
- [ ] Phase 4b — Sidebar filters
- [ ] Phase 4c — Full detail panel
- [ ] Phase 4d — Face cluster naming UI
- [ ] Phase 4e — Duplicate review view
- [ ] Phase 4f — Bulk rename tool
- [ ] Phase 4g — Settings screen
- [ ] Phase 5 — Local backup / restore

---

## License

MIT — see [LICENSE](LICENSE)
