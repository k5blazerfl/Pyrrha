# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Single-instance IPC over a ``QLocalServer``.

A second launch hands its file arguments to the already-running instance (which
enqueues them and comes to the front) and then exits, instead of starting a
duplicate. The socket name folds in the package directory, so a working-tree run
(``./pyrrha-run``) and an installed run (``/usr/bin/pyrrha``) use *different*
sockets and never forward to each other.
"""

import hashlib
import logging
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def server_name(app_id):
    """A per-user, per-install socket name for ``app_id``."""
    tag = hashlib.sha1(os.path.dirname(__file__).encode('utf-8')).hexdigest()[:8]
    return '{}.{}'.format(app_id, tag)


def send_to_running(name, lines, timeout=800):
    """Hand ``lines`` to an already-running instance. Returns True if one was
    listening and took them (so this process should exit); False if none is."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout):
        return False
    payload = ('\n'.join(lines) + '\n').encode('utf-8')
    sock.write(payload)
    sock.flush()
    sock.waitForBytesWritten(timeout)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.UnconnectedState:
        sock.waitForDisconnected(timeout)
    return True


class SingleInstanceServer(QObject):
    """Listens for launches from other processes and emits their argument lines
    (an empty list when a bare launch just wants the window brought forward)."""

    received = Signal(list)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        QLocalServer.removeServer(name)   # clear a stale socket left by a crash
        if not self._server.listen(name):
            logging.warning('Single-instance server could not listen on %s: %s',
                             name, self._server.errorString())
        self._server.newConnection.connect(self._on_new_connection)

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            data = ''
            if conn.waitForReadyRead(800):
                data = bytes(conn.readAll()).decode('utf-8', 'replace')
            conn.disconnectFromServer()
            lines = [ln for ln in data.splitlines() if ln.strip()]
            self.received.emit(lines)
