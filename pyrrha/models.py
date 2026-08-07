# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Qt models and the album-art delegate for the song list.

These replace Pithos' ``Gtk.ListStore`` + ``CellRendererAlbumArt``.  Each row
carries the Pandora ``Song`` object plus three presentation fields that the
window keeps up to date (mirroring Pithos' ``update_song_row``): an HTML blob
of display text, a rating emblem name, and the album-art pixmap.
"""

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap, QTextDocument, QTextOption
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

ALBUM_ART_SIZE = 96
TEXT_X_PADDING = 12
EMBLEM_SIZE = 16

# Custom item-data roles.
SongRole = Qt.UserRole + 1
HtmlRole = Qt.UserRole + 2
IconRole = Qt.UserRole + 3
PixmapRole = Qt.UserRole + 4

# Map Pithos' internal rating-icon names to freedesktop icon-theme names, with
# a couple of fallbacks so something sensible shows on minimal themes.
_EMBLEM_ICONS = {
    'love': ('emblem-favorite', 'starred'),
    'ban': ('action-unavailable', 'dialog-error', 'process-stop'),
    'tired': ('appointment-soon', 'go-jump', 'media-playback-pause'),
}


def _themed_icon(names):
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QIcon()


class _Row:
    __slots__ = ('song', 'html', 'icon', 'pixmap')

    def __init__(self, song):
        self.song = song
        self.html = ''
        self.icon = None
        self.pixmap = None


class SongsModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    # -- Qt model interface ------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == SongRole:
            return row.song
        if role == HtmlRole:
            return row.html
        if role == IconRole:
            return row.icon
        if role == PixmapRole:
            return row.pixmap
        return None

    # -- convenience API used by the window --------------------------------
    def clear(self):
        if not self._rows:
            return
        self.beginRemoveRows(QModelIndex(), 0, len(self._rows) - 1)
        self._rows = []
        self.endRemoveRows()

    def append_song(self, song):
        pos = len(self._rows)
        self.beginInsertRows(QModelIndex(), pos, pos)
        self._rows.append(_Row(song))
        self.endInsertRows()

    def remove_row(self, row):
        if 0 <= row < len(self._rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._rows[row]
            self.endRemoveRows()

    def reorder(self, order):
        """Rearrange rows to the given permutation of current row indices."""
        if sorted(order) != list(range(len(self._rows))):
            return
        self.beginResetModel()
        self._rows = [self._rows[i] for i in order]
        self.endResetModel()

    def song_at(self, row):
        if 0 <= row < len(self._rows):
            return self._rows[row].song
        return None

    def __len__(self):
        return len(self._rows)

    def update_row(self, row_index, html=None, icon=..., pixmap=...):
        if not (0 <= row_index < len(self._rows)):
            return
        row = self._rows[row_index]
        if html is not None:
            row.html = html
        if icon is not ...:
            row.icon = icon
        if pixmap is not ...:
            row.pixmap = pixmap
        idx = self.index(row_index)
        self.dataChanged.emit(idx, idx)


class AlbumArtDelegate(QStyledItemDelegate):
    """Paints a row: album art (with rating emblem) at left, rich text right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generic = _themed_icon(('audio-x-generic', 'audio-x-generic-symbolic'))
        self._emblems = {name: _themed_icon(names) for name, names in _EMBLEM_ICONS.items()}

    def sizeHint(self, option, index):
        return QSize(ALBUM_ART_SIZE * 3, ALBUM_ART_SIZE)

    def paint(self, painter, option, index):
        painter.save()

        # Selection / hover background, drawn by the current style.
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, option.widget)

        selected = bool(option.state & QStyle.State_Selected)
        text_color = option.palette.highlightedText().color() if selected \
            else option.palette.text().color()

        rect = option.rect
        art_rect = rect.adjusted(0, 0, 0, 0)
        art_rect.setWidth(ALBUM_ART_SIZE)

        pixmap = index.data(PixmapRole)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            painter.drawPixmap(art_rect.x(), art_rect.y(), pixmap)
        else:
            # Default cover: muted filled square + centered generic-audio icon.
            painter.fillRect(art_rect, QColor(0, 0, 0, 40))
            if not self._generic.isNull():
                pm = self._generic.pixmap(48, 48)
                painter.drawPixmap(
                    art_rect.x() + (ALBUM_ART_SIZE - pm.width()) // 2,
                    art_rect.y() + (ALBUM_ART_SIZE - pm.height()) // 2,
                    pm,
                )

        # Rating emblem, bottom-right corner of the art.
        icon_name = index.data(IconRole)
        emblem = self._emblems.get(icon_name) if icon_name else None
        if emblem is not None and not emblem.isNull():
            ex = art_rect.x() + ALBUM_ART_SIZE - EMBLEM_SIZE - 2
            ey = art_rect.y() + ALBUM_ART_SIZE - EMBLEM_SIZE - 2
            painter.setBrush(option.palette.base())
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(ex - 2, ey - 2, EMBLEM_SIZE + 4, EMBLEM_SIZE + 4))
            painter.drawPixmap(ex, ey, emblem.pixmap(EMBLEM_SIZE, EMBLEM_SIZE))

        # Rich text to the right of the art.
        html = index.data(HtmlRole) or ''
        doc = QTextDocument()
        doc.setDefaultStyleSheet('body { color: %s; }' % text_color.name())
        doc.setHtml('<body>%s</body>' % html)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.NoWrap)
        doc.setDefaultTextOption(opt)
        doc.setTextWidth(rect.width() - ALBUM_ART_SIZE - TEXT_X_PADDING * 2)

        painter.translate(rect.x() + ALBUM_ART_SIZE + TEXT_X_PADDING, rect.y() + 6)
        doc.drawContents(painter)

        painter.restore()
