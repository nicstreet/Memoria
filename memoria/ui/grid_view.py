from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QInputDialog, QListView, QMenu, QStyledItemDelegate, QStyleOptionViewItem,
)

from memoria.config import CARD_WIDTH
from memoria.ui.thumbnail_cache import ThumbnailCache

log = logging.getLogger(__name__)

LABEL_HEIGHT = 48   # pixels reserved for filename + date below the thumbnail


def _card_height(card_width: int) -> int:
    return card_width + LABEL_HEIGHT


# Roles
ROLE_FILE_ID   = Qt.ItemDataRole.UserRole + 1
ROLE_FILEPATH  = Qt.ItemDataRole.UserRole + 2
ROLE_FILENAME  = Qt.ItemDataRole.UserRole + 3
ROLE_FILE_TYPE = Qt.ItemDataRole.UserRole + 4
ROLE_DATE      = Qt.ItemDataRole.UserRole + 5
ROLE_PIXMAP    = Qt.ItemDataRole.UserRole + 6


class PhotoGridModel(QAbstractListModel):
    def __init__(self, thumbnail_cache: ThumbnailCache, parent=None):
        super().__init__(parent)
        self._records: list[dict] = []
        self._cache = thumbnail_cache
        self._cache.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._id_to_row: dict[int, int] = {}
        self._card_width = CARD_WIDTH

    def load_records(self, records: list[dict]):
        self.beginResetModel()
        self._records = records
        self._id_to_row = {r["id"]: i for i, r in enumerate(records)}
        self.endResetModel()

    def set_card_width(self, width: int):
        self._card_width = width
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._records)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r = self._records[index.row()]

        if role == ROLE_FILE_ID:   return r["id"]
        if role == ROLE_FILEPATH:  return r["filepath"]
        if role == ROLE_FILENAME:  return r["filename"]
        if role == ROLE_FILE_TYPE: return r["file_type"]
        if role == ROLE_DATE:      return r.get("date_taken")
        if role == ROLE_PIXMAP:
            return self._cache.get(r["id"], r["filepath"], r["file_type"])
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(self._card_width, _card_height(self._card_width))
        return None

    def _on_thumbnail_ready(self, file_id: int, _px: QPixmap):
        row = self._id_to_row.get(file_id)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [ROLE_PIXMAP])


# Overlay icon geometry — size is proportional to card width
_ICON_MARGIN_FRAC = 0.05   # margin as fraction of card width
_ICON_SIZE_FRAC   = 0.14   # icon size as fraction of card width
_ICON_MIN         = 18     # minimum px
_ICON_MAX         = 28     # maximum px (don't cover too much at large sizes)
_ICON_GAP         = 3


def _icon_size(card_width: int) -> int:
    return max(_ICON_MIN, min(_ICON_MAX, int(card_width * _ICON_SIZE_FRAC)))


def _icon_margin(card_width: int) -> int:
    return max(3, int(card_width * _ICON_MARGIN_FRAC))


def _rot_icon_rect(card_rect: QRect) -> QRect:
    s = _icon_size(card_rect.width())
    m = _icon_margin(card_rect.width())
    return QRect(card_rect.left() + m, card_rect.top() + m, s, s)


def _face_icon_rect(card_rect: QRect) -> QRect:
    s = _icon_size(card_rect.width())
    m = _icon_margin(card_rect.width())
    return QRect(card_rect.left() + m + s + _ICON_GAP, card_rect.top() + m, s, s)


def _nodup_icon_rect(card_rect: QRect) -> QRect:
    s = _icon_size(card_rect.width())
    m = _icon_margin(card_rect.width())
    return QRect(card_rect.left() + m + (s + _ICON_GAP) * 2, card_rect.top() + m, s, s)




class PhotoDelegate(QStyledItemDelegate):
    """Renders each photo/video as a dark card with thumbnail + label."""

    RADIUS = 4
    PADDING = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._card_width   = CARD_WIDTH
        self._hovered_row  = -1
        self._duplicate_ids: set[int] = set()   # file IDs that have unreviewed duplicates

    def set_card_width(self, width: int):
        self._card_width = width

    def set_hovered_row(self, row: int):
        self._hovered_row = row

    def set_duplicate_ids(self, ids: set[int]):
        self._duplicate_ids = ids

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & option.state.State_Selected)

        # Card background
        bg = QColor("#3a3a6a") if selected else QColor("#2d2d2d")
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        # Thumbnail
        px: QPixmap | None = index.data(ROLE_PIXMAP)
        thumb_rect = rect.adjusted(0, 0, 0, -LABEL_HEIGHT)
        if px and not px.isNull():
            painter.drawPixmap(thumb_rect, px)
        else:
            painter.fillRect(thumb_rect, QColor("#222222"))

        # Video badge
        if index.data(ROLE_FILE_TYPE) == "video":
            badge_rect = thumb_rect.adjusted(thumb_rect.width() - 36, thumb_rect.height() - 22, -4, -4)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setPen(QPen(QColor("#ffffff")))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "▶ VIDEO")

        # Overlay icons — visible on hover, photos only
        if index.row() == self._hovered_row and index.data(ROLE_FILE_TYPE) == "photo":
            from memoria.ui.fluent_icons import fi, FONT_NAME
            fi_font = QFont(FONT_NAME, 11)   # fixed small size — glyphs look clean at 11px
            painter.setPen(Qt.PenStyle.NoPen)

            def _icon_pill(icon_rect, glyph):
                painter.setBrush(QColor(0, 0, 0, 170))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(icon_rect, 6, 6)
                painter.setFont(fi_font)
                painter.setPen(QPen(QColor("#ffffff")))
                painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, glyph)

            _icon_pill(_rot_icon_rect(rect),  fi.ROTATE)
            _icon_pill(_face_icon_rect(rect), fi.PERSON)

            file_id = index.data(ROLE_FILE_ID)
            if file_id in self._duplicate_ids:
                _icon_pill(_nodup_icon_rect(rect), fi.COPY_X)

        # Label area
        label_rect = rect.adjusted(self.PADDING, rect.height() - LABEL_HEIGHT + 4,
                                   -self.PADDING, -4)

        filename = index.data(ROLE_FILENAME) or ""
        max_chars = max(10, self._card_width // 10)
        if len(filename) > max_chars:
            filename = filename[:max_chars - 2] + "…"

        date = index.data(ROLE_DATE)
        date_str = date.strftime("%Y-%m-%d") if date else ""

        font_size = max(8, min(10, self._card_width // 22))
        painter.setPen(QPen(QColor("#e0e0e0")))
        painter.setFont(QFont("Segoe UI", font_size))
        painter.drawText(label_rect.adjusted(0, 0, 0, -18), Qt.AlignmentFlag.AlignLeft, filename)

        painter.setPen(QPen(QColor("#888888")))
        painter.setFont(QFont("Segoe UI", max(8, font_size - 1)))
        painter.drawText(label_rect.adjusted(0, 18, 0, 0), Qt.AlignmentFlag.AlignLeft, date_str)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(self._card_width, _card_height(self._card_width))


class PhotoGridView(QListView):
    file_selected           = pyqtSignal(dict)
    rotate_requested        = pyqtSignal(dict)
    face_review_requested   = pyqtSignal(dict)
    not_duplicate_requested = pyqtSignal(dict)
    meta_field_changed      = pyqtSignal(int, str, str)   # file_id, field, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self._delegate = PhotoDelegate(self)
        self.setItemDelegate(self._delegate)
        self._hovered_index = QModelIndex()

    def set_model(self, model: PhotoGridModel):
        self._grid_model = model
        self.setModel(model)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_card_width(self, width: int):
        self._delegate.set_card_width(width)
        if hasattr(self, "_grid_model"):
            self._grid_model.set_card_width(width)
        self.setGridSize(QSize(width, _card_height(width)))
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def set_duplicate_ids(self, ids: set[int]):
        self._delegate.set_duplicate_ids(ids)
        self.viewport().update()

    # ── Hover tracking ────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        idx = self.indexAt(event.pos())
        if idx != self._hovered_index:
            old_row = self._hovered_index.row()
            self._hovered_index = idx
            self._delegate.set_hovered_row(idx.row() if idx.isValid() else -1)
            # Repaint old and new rows
            if old_row >= 0 and hasattr(self, "_grid_model"):
                old_idx = self._grid_model.index(old_row)
                self.update(old_idx)
            if idx.isValid():
                self.update(idx)
            # Cursor: hand if over any overlay icon, else default
            if idx.isValid() and idx.data(ROLE_FILE_TYPE) == "photo":
                card_rect = self.visualRect(idx)
                pos = event.pos()
                file_id = idx.data(ROLE_FILE_ID)
                if (_rot_icon_rect(card_rect).contains(pos)
                        or _face_icon_rect(card_rect).contains(pos)
                        or (file_id in self._delegate._duplicate_ids
                            and _nodup_icon_rect(card_rect).contains(pos))):
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                    super().mouseMoveEvent(event)
                    return
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered_index.isValid():
            old = self._hovered_index
            self._hovered_index = QModelIndex()
            self._delegate.set_hovered_row(-1)
            self.update(old)
        super().leaveEvent(event)

    # ── Click: intercept rotate icon hit ─────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(event.pos())
            if idx.isValid() and idx.data(ROLE_FILE_TYPE) == "photo":
                card_rect = self.visualRect(idx)
                pos = event.pos()
                record = self._record_from_index(idx)
                if _rot_icon_rect(card_rect).contains(pos):
                    self.rotate_requested.emit(record)
                    return
                if _face_icon_rect(card_rect).contains(pos):
                    self.face_review_requested.emit(record)
                    return
                if (_nodup_icon_rect(card_rect).contains(pos)
                        and record["id"] in self._delegate._duplicate_ids):
                    self.not_duplicate_requested.emit(record)
                    return
        super().mousePressEvent(event)

    # ── Context menu ─────────────────────────────────────────────────────────

    def contextMenuEvent(self, event):
        idx = self.indexAt(event.pos())
        if not idx.isValid() or idx.data(ROLE_FILE_TYPE) != "photo":
            return

        record = self._record_from_index(idx)
        has_dupes = record["id"] in self._delegate._duplicate_ids

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #252526; color: #d4d4d4;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 0;
            }
            QMenu::item { padding: 6px 28px 6px 14px; font-size: 12px; }
            QMenu::item:selected { background: #5a4fd4; color: #fff; }
            QMenu::item:disabled { color: #555; }
            QMenu::separator { height: 1px; background: #444; margin: 4px 0; }
        """)

        rotate_act = menu.addAction("Rotate 90° clockwise")
        rotate_act.triggered.connect(lambda: self.rotate_requested.emit(record))

        face_act = menu.addAction("Review Faces")
        face_act.triggered.connect(lambda: self.face_review_requested.emit(record))

        menu.addSeparator()

        title_act = menu.addAction("Set Title…")
        title_act.triggered.connect(lambda: self._prompt_meta(record, "title"))

        subject_act = menu.addAction("Set Subject…")
        subject_act.triggered.connect(lambda: self._prompt_meta(record, "subject"))

        if has_dupes:
            menu.addSeparator()
            nodup_act = menu.addAction("≠  Mark as not a duplicate")
            nodup_act.triggered.connect(
                lambda: self.not_duplicate_requested.emit(record)
            )

        menu.exec(event.globalPos())

    def _prompt_meta(self, record: dict, field: str):
        """Show an input dialog for title or subject and emit meta_field_changed."""
        label = "Title" if field == "title" else "Subject"
        text, ok = QInputDialog.getText(
            self, f"Set {label}",
            f"Enter {label} for {record['filename']}:",
        )
        if ok:
            self.meta_field_changed.emit(record["id"], field, text.strip())

    def _record_from_index(self, idx: QModelIndex) -> dict:
        return {
            "id":        idx.data(ROLE_FILE_ID),
            "filepath":  idx.data(ROLE_FILEPATH),
            "filename":  idx.data(ROLE_FILENAME),
            "file_type": idx.data(ROLE_FILE_TYPE),
        }

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex):
        if current.isValid():
            record = {
                "id":         current.data(ROLE_FILE_ID),
                "filepath":   current.data(ROLE_FILEPATH),
                "filename":   current.data(ROLE_FILENAME),
                "file_type":  current.data(ROLE_FILE_TYPE),
                "date_taken": current.data(ROLE_DATE),
            }
            self.file_selected.emit(record)
