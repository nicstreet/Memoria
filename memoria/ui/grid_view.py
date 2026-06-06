from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import (
    QAbstractListModel, QModelIndex, QSize, Qt, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem

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


class PhotoDelegate(QStyledItemDelegate):
    """Renders each photo/video as a dark card with thumbnail + label."""

    RADIUS = 4
    PADDING = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._card_width = CARD_WIDTH

    def set_card_width(self, width: int):
        self._card_width = width

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
    file_selected = pyqtSignal(dict)

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

        self._delegate = PhotoDelegate(self)
        self.setItemDelegate(self._delegate)

    def set_model(self, model: PhotoGridModel):
        self._grid_model = model
        self.setModel(model)
        self.selectionModel().currentChanged.connect(self._on_current_changed)

    def set_card_width(self, width: int):
        self._delegate.set_card_width(width)
        if hasattr(self, "_grid_model"):
            self._grid_model.set_card_width(width)
        # setGridSize tells Qt exactly how wide each cell is — no internal rounding
        self.setGridSize(QSize(width, _card_height(width)))
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

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
