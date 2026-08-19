// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
#include <QApplication>

#include "ui/MainWindow.h"

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("Pyrrha"));
    app.setApplicationDisplayName(QStringLiteral("Pyrrha"));
    app.setDesktopFileName(QStringLiteral("io.github.k5blazerfl.Pyrrha"));

    pyrrha::MainWindow window;
    window.show();
    return app.exec();
}
