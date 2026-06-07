import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor

from memoria.config import THUMBNAILS_DIR, THUMBNAIL_SIZE

log = logging.getLogger(__name__)

_PLACEHOLDER: QPixmap | None = None


def placeholder_pixmap() -> QPixmap:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        px = QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        px.fill(QColor("#2d2d2d"))
        _PLACEHOLDER = px
    return _PLACEHOLDER


def _thumb_path(file_id: int) -> Path:
    return THUMBNAILS_DIR / f"{file_id}.jpg"


def load_cached(file_id: int) -> QPixmap | None:
    p = _thumb_path(file_id)
    if p.exists():
        px = QPixmap(str(p))
        if not px.isNull():
            return px
    return None


class _WorkerSignals(QObject):
    done = pyqtSignal(int, QPixmap)   # file_id, pixmap
    error = pyqtSignal(int)           # file_id


class ThumbnailWorker(QRunnable):
    def __init__(self, file_id: int, filepath: str, file_type: str):
        super().__init__()
        self.file_id = file_id
        self.filepath = filepath
        self.file_type = file_type
        self.signals = _WorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            px = self._generate()
            if px and not px.isNull():
                px.save(str(_thumb_path(self.file_id)), "JPEG", 85)
                self.signals.done.emit(self.file_id, px)
            else:
                self.signals.error.emit(self.file_id)
        except Exception as e:
            log.debug(f"Thumbnail generation failed for file {self.file_id}: {e}")
            self.signals.error.emit(self.file_id)

    def _generate(self) -> QPixmap | None:
        if self.file_type == "photo":
            px = self._from_image()
            if px:
                px = self._correct_orientation(px)
            return px
        else:
            return self._from_video()

    def _correct_orientation(self, px: QPixmap) -> QPixmap:
        """Rotate thumbnail to match EXIF orientation tag."""
        try:
            import exifread
            from PyQt6.QtGui import QTransform
            with open(self.filepath, "rb") as f:
                tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
            tag = tags.get("Image Orientation")
            if tag is None:
                return px
            val = tag.values[0] if tag.values else 1
            t = QTransform()
            if val == 3:   t.rotate(180)
            elif val == 6: t.rotate(90)
            elif val == 8: t.rotate(-90)
            if val not in (1, 2, 4, 5, 7):
                return px.transformed(t, Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
        return px

    def _from_image(self) -> QPixmap | None:
        img = QImage(self.filepath)
        if img.isNull():
            # Fallback via Pillow for formats Qt doesn't handle (HEIC, RAW, etc.)
            try:
                from PIL import Image as PILImage
                import io
                with PILImage.open(self.filepath) as pil:
                    pil.thumbnail((THUMBNAIL_SIZE * 2, THUMBNAIL_SIZE * 2))
                    buf = io.BytesIO()
                    pil.convert("RGB").save(buf, format="JPEG")
                    img = QImage()
                    img.loadFromData(buf.getvalue())
            except Exception:
                return None
        if img.isNull():
            return None
        px = QPixmap.fromImage(img)
        return _square_crop(px, THUMBNAIL_SIZE)

    def _from_video(self) -> QPixmap | None:
        try:
            import ffmpeg
            out, _ = (
                ffmpeg.input(self.filepath, ss=2)
                .output("pipe:", vframes=1, format="image2", vcodec="mjpeg")
                .run(capture_stdout=True, capture_stderr=True)
            )
            img = QImage()
            img.loadFromData(out)
            if img.isNull():
                return None
            px = QPixmap.fromImage(img)
            return _square_crop(px, THUMBNAIL_SIZE)
        except Exception:
            return None


def _square_crop(px: QPixmap, size: int) -> QPixmap:
    """Scale to fill a square then centre-crop."""
    scaled = px.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    x = (scaled.width() - size) // 2
    y = (scaled.height() - size) // 2
    return scaled.copy(x, y, size, size)


class ThumbnailCache(QObject):
    """
    Thread-safe thumbnail cache.
    Call request(file_id, filepath, file_type) to get a pixmap or queue generation.
    Connect thumbnail_ready(file_id, QPixmap) to update your model.
    """
    thumbnail_ready = pyqtSignal(int, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[int, QPixmap] = {}
        self._pending: set[int] = set()
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(4)

    def get(self, file_id: int, filepath: str, file_type: str) -> QPixmap:
        """Return cached pixmap immediately, or placeholder while generation queues."""
        if file_id in self._cache:
            return self._cache[file_id]

        # Try disk cache first (fast, synchronous)
        disk = load_cached(file_id)
        if disk:
            self._cache[file_id] = disk
            return disk

        # Queue background generation
        if file_id not in self._pending:
            self._pending.add(file_id)
            worker = ThumbnailWorker(file_id, filepath, file_type)
            worker.signals.done.connect(self._on_done)
            worker.signals.error.connect(self._on_error)
            self._pool.start(worker)

        return placeholder_pixmap()

    def _on_done(self, file_id: int, px: QPixmap):
        self._cache[file_id] = px
        self._pending.discard(file_id)
        self.thumbnail_ready.emit(file_id, px)

    def invalidate(self, file_id: int, filepath: str, file_type: str):
        """Evict from memory + disk cache, then re-queue thumbnail generation."""
        self._cache.pop(file_id, None)
        self._pending.discard(file_id)
        disk = _thumb_path(file_id)
        if disk.exists():
            try:
                disk.unlink()
            except OSError:
                pass
        # Re-generate immediately so the grid updates
        self._pending.add(file_id)
        worker = ThumbnailWorker(file_id, filepath, file_type)
        worker.signals.done.connect(self._on_done)
        worker.signals.error.connect(self._on_error)
        self._pool.start(worker)

    def _on_error(self, file_id: int):
        self._pending.discard(file_id)
        self._cache[file_id] = placeholder_pixmap()
