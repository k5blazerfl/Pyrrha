# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Internet-radio browser.

A tabbed dialog over the RadioBrowser directory: a **Browse** tab (free-text
search plus genre and country filters) and a **Favourites** tab backed by the
saved-stations file. Selecting a station tunes it in the main window (which
switches to the radio source); stations can be starred into / removed from the
favourites list here or from the song-list context menu.
"""

import logging

from gi.repository import GLib
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import radio, radiobrowser

LOGO_SIZE = 24


class RadioDialog(QDialog):
    """Search RadioBrowser, manage favourites, and tune stations."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Internet Radio'))
        self.window = window
        self.worker_run = window.worker_run
        self._results = []          # Browse tab: normalised station dicts
        self._favorites = []        # Favourites tab: RadioStation objects
        self._ready = False         # gate filter-driven searches during setup
        self._logo_cache = {}       # favicon URL -> QPixmap (or False on failure)
        self._logo_gen = {}         # id(table) -> current generation token
        self.resize(600, 460)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_browse_tab(), _('Browse'))
        self.tabs.addTab(self._build_favorites_tab(), _('Favourites'))
        self.tabs.currentChanged.connect(self._on_tab_changed)

        close_button = QPushButton(_('Close'))
        close_button.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addLayout(bottom)

        # Populate filter dropdowns, then land on the most popular stations.
        self._populate_filters()
        self.refresh_favorites()
        self._load(self._current_fetch())
        self._ready = True

    # -- Browse tab -------------------------------------------------------
    def _build_browse_tab(self):
        w = QWidget()
        self.query = QLineEdit()
        self.query.setPlaceholderText(_('Search stations by name…'))
        self.query.returnPressed.connect(self.do_search)

        self.genre = QComboBox()
        self.genre.addItem(_('All genres'), '')
        self.genre.currentIndexChanged.connect(self._on_filter_changed)
        self.country = QComboBox()
        self.country.addItem(_('All countries'), '')
        self.country.currentIndexChanged.connect(self._on_filter_changed)

        self.search_button = QPushButton(_('Search'))
        self.search_button.clicked.connect(self.do_search)

        search_row = QHBoxLayout()
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.genre)
        search_row.addWidget(self.country)
        search_row.addWidget(self.search_button)

        self.table = self._make_table([_('Station'), _('Genre'), _('Bitrate')])
        self.table.doubleClicked.connect(lambda *_: self.play_selected())
        self.table.itemSelectionChanged.connect(self._update_favorite_button)

        self.favorite_button = QPushButton(_('Add to Favourites'))
        self.favorite_button.clicked.connect(self.favorite_selected)
        self.play_button = QPushButton(_('Play'))
        self.play_button.clicked.connect(self.play_selected)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.favorite_button)
        button_row.addWidget(self.play_button)

        layout = QVBoxLayout(w)
        layout.addLayout(search_row)
        layout.addWidget(self.table)
        layout.addLayout(button_row)
        return w

    # -- Favourites tab ---------------------------------------------------
    def _build_favorites_tab(self):
        w = QWidget()
        self.fav_table = self._make_table([_('Station'), _('Genre')])
        self.fav_table.doubleClicked.connect(lambda *_: self.play_favorite())

        self.restore_button = QPushButton(_('Restore Defaults'))
        self.restore_button.setToolTip(_('Add the built-in default stations'))
        self.restore_button.clicked.connect(self.restore_defaults)
        self.remove_button = QPushButton(_('Remove'))
        self.remove_button.clicked.connect(self.remove_favorite)
        self.fav_play_button = QPushButton(_('Play'))
        self.fav_play_button.clicked.connect(self.play_favorite)
        button_row = QHBoxLayout()
        button_row.addWidget(self.restore_button)
        button_row.addStretch(1)
        button_row.addWidget(self.remove_button)
        button_row.addWidget(self.fav_play_button)

        layout = QVBoxLayout(w)
        layout.addWidget(self.fav_table)
        layout.addLayout(button_row)
        return w

    @staticmethod
    def _make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setIconSize(QSize(LOGO_SIZE, LOGO_SIZE))
        return table

    # -- filters ----------------------------------------------------------
    def _populate_filters(self):
        proxy = self.window.get_proxy()
        self.worker_run(radiobrowser.tags, (100, proxy), self._set_genres,
                        context=None, errorback=self._ignore_error)
        self.worker_run(radiobrowser.countries, (proxy,), self._set_countries,
                        context=None, errorback=self._ignore_error)

    def _set_genres(self, names):
        self.genre.blockSignals(True)
        for name in names or []:
            self.genre.addItem(name, name)
        self.genre.blockSignals(False)

    def _set_countries(self, entries):
        self.country.blockSignals(True)
        for c in entries or []:
            self.country.addItem(c['name'], c['code'])
        self.country.blockSignals(False)

    def _on_filter_changed(self, *ignore):
        if self._ready:
            self.do_search()

    # -- search -----------------------------------------------------------
    def _current_fetch(self):
        """Build the fetch callable for the current query + filter selection."""
        proxy = self.window.get_proxy()
        q = self.query.text().strip()
        genre = self.genre.currentData() or ''
        cc = self.country.currentData() or ''
        if not q and not genre and not cc:
            return lambda: radiobrowser.top_stations(limit=100, proxy=proxy)
        if q and not genre and not cc:
            # A bare term: match it against both names and genre tags so e.g.
            # "jazz" finds jazz stations without touching the genre dropdown.
            def fetch():
                by_name = radiobrowser.search(query=q, limit=100, proxy=proxy)
                by_tag = radiobrowser.search(tag=q, limit=100, proxy=proxy)
                seen = {s['uuid'] for s in by_name if s.get('uuid')}
                return by_name + [s for s in by_tag if s.get('uuid') not in seen]
            return fetch
        return lambda: radiobrowser.search(query=q, tag=genre, countrycode=cc,
                                           limit=100, proxy=proxy)

    def do_search(self):
        self._load(self._current_fetch())

    def _load(self, fetch):
        self.search_button.setEnabled(False)
        self.worker_run(fetch, (), self._populate, _('Searching stations…'),
                        errorback=self._search_failed)

    def _populate(self, results):
        self.search_button.setEnabled(True)
        self._results = results or []
        self.table.setRowCount(len(self._results))
        for row, s in enumerate(self._results):
            bitrate = '%d kbps' % s['bitrate'] if s.get('bitrate') else ''
            genre = (s.get('tags') or '').replace(',', ', ')
            self._fill_row(self.table, row, (s.get('name', ''), genre, bitrate))
        self._load_logos(self.table,
                         [(r, s.get('favicon', '')) for r, s in enumerate(self._results)])
        self._update_favorite_button()
        if not self._results:
            QMessageBox.information(self, _('Internet Radio'),
                                    _('No stations found.'))

    def _search_failed(self, error):
        self.search_button.setEnabled(True)
        self.window.status_pop('net')   # custom errorback bypasses worker_run's pop
        logging.warning('RadioBrowser search failed: %s', error)
        QMessageBox.warning(self, _('Internet Radio'),
                            _('Could not reach the station directory.'))

    def _ignore_error(self, error):
        # Filter dropdowns are non-critical; a failure just leaves "All …".
        logging.info('RadioBrowser filter load failed: %s', error)

    @staticmethod
    def _fill_row(table, row, texts):
        for col, text in enumerate(texts):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            table.setItem(row, col, item)

    # -- station logos ----------------------------------------------------
    def _load_logos(self, table, rows):
        """Fetch favicons for ``rows`` (list of ``(row_index, url)``) and set
        them as the Station-column icons. Cached logos apply immediately; the
        rest load on a single background thread, posting each back as it lands.
        A per-table generation token discards results from a stale population."""
        idt = id(table)
        gen = self._logo_gen.get(idt, 0) + 1
        self._logo_gen[idt] = gen
        proxy = self.window.get_proxy()
        misses = []
        for row, url in rows:
            if not url:
                continue
            pm = self._logo_cache.get(url)
            if pm is None:
                misses.append((row, url))
            elif pm:
                self._apply_icon(table, row, pm)
        if not misses:
            return

        def work():
            for row, url in misses:
                if self._logo_gen.get(idt) != gen:
                    return          # table repopulated; stop fetching
                try:
                    data = radiobrowser.fetch_image(url, proxy)
                except Exception:
                    data = None
                GLib.idle_add(self._logo_ready, idt, gen, table, row, url, data)

        self.worker_run(work, (), None, context=None, errorback=self._ignore_error)

    def _logo_ready(self, idt, gen, table, row, url, data):
        if self._logo_gen.get(idt) != gen:
            return False            # stale
        pm = False
        if data:
            p = QPixmap()
            if p.loadFromData(data) and not p.isNull():
                pm = p.scaled(LOGO_SIZE, LOGO_SIZE, Qt.KeepAspectRatio,
                              Qt.SmoothTransformation)
        self._logo_cache[url] = pm
        if pm:
            self._apply_icon(table, row, pm)
        return False                # one-shot idle callback

    @staticmethod
    def _apply_icon(table, row, pm):
        item = table.item(row, 0)
        if item is not None:
            item.setIcon(QIcon(pm))

    # -- favourites -------------------------------------------------------
    def refresh_favorites(self):
        self._favorites = radio.load_favorites()
        self.fav_table.setRowCount(len(self._favorites))
        for row, s in enumerate(self._favorites):
            genre = (s.station_tags or '').replace(',', ', ')
            self._fill_row(self.fav_table, row, (s.name, genre))
        self._load_logos(self.fav_table,
                         [(r, s.favicon or '') for r, s in enumerate(self._favorites)])
        self._update_favorite_button()

    def _on_tab_changed(self, index):
        if self.tabs.tabText(index) == _('Favourites'):
            self.refresh_favorites()

    def _update_favorite_button(self, *ignore):
        station = self._selected_station()
        already = station is not None and self.window.is_radio_favorite(station)
        self.favorite_button.setEnabled(station is not None and not already)
        self.favorite_button.setText(
            _('In Favourites') if already else _('Add to Favourites'))

    # -- actions ----------------------------------------------------------
    def _selected_station(self):
        row = self.table.currentRow()
        if not (0 <= row < len(self._results)):
            return None
        station = radio.RadioStation.from_dict(self._results[row])
        return station if station.audioUrl else None

    def _selected_favorite(self):
        row = self.fav_table.currentRow()
        if 0 <= row < len(self._favorites):
            return self._favorites[row]
        return None

    def play_selected(self):
        station = self._selected_station()
        if station is not None:
            self.window.tune_radio(station)
            self.accept()

    def favorite_selected(self):
        station = self._selected_station()
        if station is not None:
            self.window.add_radio_favorite(station)
            self.refresh_favorites()

    def play_favorite(self):
        station = self._selected_favorite()
        if station is not None:
            self.window.tune_radio(station)
            self.accept()

    def remove_favorite(self):
        station = self._selected_favorite()
        if station is not None:
            self.window.remove_radio_favorite(station)
            self.refresh_favorites()

    def restore_defaults(self):
        radio.restore_defaults()
        self.refresh_favorites()
