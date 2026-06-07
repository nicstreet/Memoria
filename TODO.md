# Memoria — TODO

> Canonical version: Notes Vault / Memoria - Development.md
> Work through one stage at a time in order. Each stage should feel complete before moving on.

---

## Stage 1 — UI Foundation & Polish ✅
*Make the existing app look and feel finished. No new functionality — just tightening what's there.*

- [x] **Frameless window** — OS title bar removed; custom `_TopBar` with drag, min/max/close
- [x] **Options layout tidy-up:**
  - [x] Card-row style already in place; controls stack correctly
  - [x] Number inputs: spinner arrows hidden (width:0 CSS)
  - [x] Subject manager moved to full-width layout in Editor page
- [x] **Panel widths & padding:**
  - [x] Sidebar min-width 240px, detail panel min-width 260px enforced
  - [x] `_set_panel_sizes` uses `max(240, …)` / `max(260, …)`
- [x] **Menus restructured:** File / Edit / Help (embedded in title bar menu bar)
  - [x] File: Open Folder, Re-Index (Ctrl+R), Quit
  - [x] Edit: Bulk Edit, Review Duplicates, Name Faces, People, Re-Assess, Options
  - [x] Help: About Memoria (version, DB size, PyQt6, DeepFace, face model, icons)
- [x] **Options — Library page:** watched folder list with Add / Remove folder buttons
- [x] **Toolbar above photo grid:** Select All / Select None buttons

---

## Stage 2 — Collapsible Navigation & Sidebar Rail
*Implement the Windows Photos-style navigation rail.*

- [ ] Collapsible left icon rail:
  - [ ] Collapsed state: narrow strip, icons only
  - [ ] Expanded state: icon + label per item
  - [ ] Hamburger toggle button at top of rail
  - [ ] Animate / snap between states
- [ ] Rail items: Gallery, Favourites, People, Albums, Folders (This PC)
- [ ] `is_favourite` field added to `files` DB table
- [ ] Favourites rail item filters to favourited photos
- [ ] Appearance setting: Menu style — Text / Icons only / Icons + Text

---

## Stage 3 — Viewer & Keyboard Navigation
*Single-photo view and keyboard-driven workflows — essential for reviewing a shoot.*

- [ ] **Fullscreen / lightbox viewer:**
  - [ ] Open on double-click or Enter key
  - [ ] Zoom in/out (Ctrl+scroll or +/-)
  - [ ] Pan (drag when zoomed)
  - [ ] Prev / Next photo (arrow keys or on-screen buttons)
  - [ ] Close on Escape
  - [ ] Show basic metadata overlay (filename, date, rating) in corner
- [ ] **Keyboard navigation in grid:**
  - [ ] Arrow keys move selection
  - [ ] Enter opens lightbox
  - [ ] F toggles fullscreen lightbox
- [ ] **Video playback:**
  - [ ] Double-click video opens it with the system default player

---

## Stage 4 — Multi-Select & Culling
*The foundation of all bulk operations. Ratings and labels for culling a shoot.*

- [ ] **Multi-select in grid:**
  - [ ] Ctrl+click to toggle individual items
  - [ ] Shift+click for range select
  - [ ] Select All / Select None (toolbar buttons + Ctrl+A / Escape)
  - [ ] Visual selection state on cards (highlight border / overlay)
  - [ ] Status bar shows "X selected"
- [ ] **Star ratings (1–5):**
  - [ ] `rating` field added to `metadata` DB table
  - [ ] Set rating from detail panel, lightbox, or keyboard (keys 1–5, 0 to clear)
  - [ ] Rating displayed on grid card (stars or dot indicator)
  - [ ] Filter sidebar: filter by minimum rating
- [ ] **Colour labels:**
  - [ ] `colour_label` field added to `metadata` DB table (Red / Yellow / Green / Blue / Purple / None)
  - [ ] Set label from detail panel, lightbox, or right-click context menu
  - [ ] Label shown as colour dot/border on grid card
  - [ ] Filter sidebar: filter by label
- [ ] **Pick / Reject flags:**
  - [ ] P to pick, X to reject (standard culling shortcuts)
  - [ ] Rejected photos shown with dim overlay in grid
  - [ ] Filter to show only picked / only rejected
- [ ] **Soft-delete / Trash:**
  - [ ] `trashed` field added to `files` DB table
  - [ ] "Move to trash" action — hides from grid, moves file to OS recycle bin
  - [ ] "Empty trash" — permanent delete of trashed files
  - [ ] Trashed photos excluded from all views by default; optional "show trash" filter
- [ ] **Compare view:**
  - [ ] Select 2–4 photos → Compare mode shows them side by side
  - [ ] Sync zoom/pan across panels
  - [ ] Pick/reject/rate from compare view

---

## Stage 5 — Bulk Operations
*Depends on multi-select (Stage 4). Full power bulk editing.*

- [ ] **Bulk operations apply to current selection** (if any) or current filter (if no selection)
- [ ] **Bulk Title** — apply a single title to all selected photos
- [ ] **Bulk Subject** — apply a subject with type-ahead completer
- [ ] **Bulk Tag** — add one or more tags; option to replace or append
- [ ] **Bulk Rating** — set star rating on selection
- [ ] **Bulk Colour Label** — set label on selection
- [ ] **Bulk Rename** — rename with format string + incremental counter:
  - [ ] Format builder UI: tokens for date, subject, title, counter, original name
  - [ ] Preview before applying (show old → new name for first 5 files)
  - [ ] Counter: configurable start, step, zero-padding (e.g. `001`, `01`, `1`)
- [ ] **Bulk Copyright / Artist** — apply `XMP:Rights`, `EXIF:Artist` fields
- [ ] **Bulk Date Shift** — shift date taken ±N hours/days (timezone/clock correction)
- [ ] **Bulk GPS assign** — set lat/lon on selection + reverse-geocode to location label
- [ ] **Bulk GPS clear** — strip GPS from selection (privacy)
- [ ] **Bulk caption** — apply a shared long-form description
- [ ] **Metadata template** — save a named set of field values; apply in one click
  - [ ] Template fields: title, subject, tags, copyright, artist, location, rating, label
  - [ ] Manage templates (create / rename / delete) from Options > Editor

---

## Stage 6 — Face Workflow Improvements
*Depends on Stage 1 (UI polish) and existing face pipeline.*

- [ ] **Bulk cluster naming UI:**
  - [ ] Dedicated "Faces" view (via rail) showing all unnamed clusters as face-tile grid
  - [ ] Click a cluster → see all face crops from that cluster
  - [ ] Assign name or merge into existing person from this view
  - [ ] Show "possible match" suggestion (nearest known person by embedding distance)
- [ ] **Ignore / suppress a face detection:**
  - [ ] Right-click a face in Face Review → "Not a person / ignore"
  - [ ] Ignored detections excluded from all cluster/match passes
- [ ] **Merge people records:**
  - [ ] Select two person records in Persons dialog → Merge → all detections and tags consolidated
- [ ] **Options — AI Configuration page:**
  - [ ] Match Threshold slider (default 0.6) — "Face match sensitivity"
  - [ ] Cluster Threshold slider (default 0.4) — "Cluster grouping sensitivity"
  - [ ] Minimum Cluster Size spinner (default 2)
  - [ ] Detection Model dropdown (ArcFace / Facenet512 / VGG-Face)
  - [ ] Detector Backend dropdown (retinaface / mtcnn / opencv)
  - [ ] Plain-English description next to each control
  - [ ] "Reset to defaults" button
  - [ ] Settings saved to `ui_settings.json` and read at runtime (not hard-coded)

---

## Stage 7 — Library Organisation
*Albums, smart collections, saved searches, dashboard.*

- [ ] **Migrate subjects** from `default_subjects.py` JSON → `subject_categories` + `subjects` DB tables
- [ ] **Manual albums:**
  - [ ] Create / rename / delete albums
  - [ ] Drag photos into album, or right-click → Add to Album
  - [ ] Albums shown under Folders in the nav rail
- [ ] **Smart albums** (rule-based):
  - [ ] Query builder: tag / person / date range / rating / label / location / subject
  - [ ] Auto-updates as library changes
- [ ] **Saved searches** — save current sidebar filter state as a named view
- [ ] **Dashboard / library health panel:**
  - [ ] Total photos / videos
  - [ ] Counts: untagged, no subject, no faces identified, duplicates pending, missing metadata
  - [ ] Quick-action buttons to jump to each category

---

## Stage 8 — Import & Geolocation
*Getting photos from camera to library with metadata applied at ingest.*

- [ ] **Import from camera / card:**
  - [ ] Browse for source folder (camera card / device)
  - [ ] Copy or move to a target watched folder
  - [ ] Rename during import (apply format string)
  - [ ] Detect and skip duplicates at import time
  - [ ] Apply a metadata template on import (copyright, tags, subject)
- [ ] **GPX track import:**
  - [ ] Load a `.gpx` file
  - [ ] Match photo timestamps to track points (with configurable timezone offset)
  - [ ] Assign lat/lon and reverse-geocode location label
- [ ] **Read existing EXIF/IPTC on import:**
  - [ ] Extract keywords → tags
  - [ ] Extract title / caption → title / subject fields
  - [ ] Extract rating → rating field
  - [ ] Extract copyright / artist → stored fields
- [ ] **RAW file support:**
  - [ ] Index `.cr2`, `.nef`, `.arw`, `.dng`, `.raf` etc.
  - [ ] Write `.xmp` sidecar files for metadata (RAW files are not directly writeable)
  - [ ] Thumbnail generation for RAW files

---

## Stage 9 — Data Safety & Audit
*Undo, history, and export — confidence to run large bulk operations.*

- [ ] **Undo last operation:**
  - [ ] Undo last bulk edit / rename / tag change
  - [ ] At minimum: undo stack for metadata writes (not file moves)
- [ ] **Edit history / activity log:**
  - [ ] DB table: `edit_log` (timestamp, operation, affected file count, field, old value, new value)
  - [ ] Viewable from Help menu
- [ ] **Metadata completeness report:**
  - [ ] Show which photos are missing: title / subject / GPS / rating / copyright
  - [ ] Exportable as CSV
- [ ] **Batch export:**
  - [ ] Export selection at target size / quality (web-ready JPEGs)
  - [ ] Apply watermark option
  - [ ] Output to a chosen folder

---

## Stage 10 — Views & Automation
*Timeline, map, folder watcher — nice-to-have views and background automation.*

- [ ] **Timeline view** — photos grouped and laid out by month/year
- [ ] **Map view** — GPS-tagged photos plotted on interactive map; click to open photo
- [ ] **Slideshow** — fullscreen auto-advance with configurable interval and transition
- [ ] **Folder watcher** — OS file system watcher; auto-triggers re-index when new files detected
- [ ] **Scheduled re-assess** — option to run face re-assess automatically overnight
