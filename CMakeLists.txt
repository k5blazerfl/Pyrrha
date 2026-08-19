# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.21)

project(pyrrha
    VERSION 0.1.0
    DESCRIPTION "A HeDE-native skinnable music player"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Native Qt6 — the same stack as the HeDE shell (Widgets, no QML). Audio comes
# from Qt6::Multimedia; the engine is isolated behind PlayerEngine so a
# GStreamer backend can be dropped in later for gapless / ReplayGain / EQ.
find_package(Qt6 REQUIRED COMPONENTS Widgets Multimedia)
# TagLib reads audio tags for every common format (incl. Ogg/Opus, which
# QMediaMetaData can't) — pure C++, no GLib.
find_package(taglib REQUIRED)
# KArchive (KF6) reads .wsz skin archives (ZIP) — Qt6-native, minimal deps.
find_package(KF6Archive REQUIRED)

add_executable(pyrrha
    src/main.cpp
    src/engine/QtAudioEngine.cpp
    src/sources/LocalSource.cpp
    src/sources/MetadataScanner.cpp
    src/skin/Skin.cpp
    src/skin/BitmapFont.cpp
    src/player/Player.cpp
    src/ui/MainWindow.cpp
    # Q_OBJECT headers listed so AUTOMOC processes them. PlayerEngine.h is
    # header-only (an abstract base with signals) and has no .cpp, so without
    # this its moc — vtable, staticMetaObject, signal emitters — is never built.
    src/engine/PlayerEngine.h
    src/engine/QtAudioEngine.h
    src/player/Player.h
    src/ui/MainWindow.h
)
target_include_directories(pyrrha PRIVATE src)
target_link_libraries(pyrrha PRIVATE Qt6::Widgets Qt6::Multimedia TagLib::tag KF6::Archive)
target_compile_options(pyrrha PRIVATE -Wall -Wextra)

install(TARGETS pyrrha RUNTIME DESTINATION bin)

# -- tests ------------------------------------------------------------------
enable_testing()
add_executable(test_skin
    tests/test_skin.cpp
    src/skin/Skin.cpp
    src/skin/BitmapFont.cpp)
target_include_directories(test_skin PRIVATE src)
target_link_libraries(test_skin PRIVATE Qt6::Gui KF6::Archive)
add_test(NAME skin COMMAND test_skin)
