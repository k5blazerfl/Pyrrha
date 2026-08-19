# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.21)

project(pyrrha
    VERSION 0.3.0
    DESCRIPTION "A HeDE-native skinnable music player"
    LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Native Qt6 — the same stack as the HeDE shell (Widgets, no QML). Audio via
# Qt6::Multimedia (QAudioDecoder + QAudioSink); DBus for MPRIS2 media integration.
find_package(Qt6 REQUIRED COMPONENTS Widgets Multimedia DBus Test)
# TagLib reads audio tags for every common format (incl. Ogg/Opus, which
# QMediaMetaData can't) — pure C++, no GLib.
find_package(taglib REQUIRED)
# KArchive (KF6) reads .wsz skin archives (ZIP) — Qt6-native, minimal deps.
find_package(KF6Archive REQUIRED)

add_executable(pyrrha
    src/main.cpp
    src/engine/QtAudioEngine.cpp
    src/engine/StreamBuffer.cpp
    src/sources/LocalSource.cpp
    src/sources/MetadataScanner.cpp
    src/skin/Skin.cpp
    src/skin/BitmapFont.cpp
    src/skin/SkinnedWindow.cpp
    src/skin/SkinnedEqWindow.cpp
    src/mpris/MprisAdapter.cpp
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
target_link_libraries(pyrrha PRIVATE
    Qt6::Widgets Qt6::Multimedia Qt6::DBus TagLib::tag KF6::Archive)
target_compile_options(pyrrha PRIVATE -Wall -Wextra)

install(TARGETS pyrrha RUNTIME DESTINATION bin)

# -- tests ------------------------------------------------------------------
# Run with: ctest --test-dir build
enable_testing()

# StreamBuffer is the streaming engine's testable core (the sink integration
# itself needs real audio hardware).
add_executable(test_streambuffer
    tests/test_streambuffer.cpp
    src/engine/StreamBuffer.cpp
    src/engine/StreamBuffer.h)
target_include_directories(test_streambuffer PRIVATE src)
target_link_libraries(test_streambuffer PRIVATE Qt6::Core)
add_test(NAME streambuffer COMMAND test_streambuffer)

# Skin loader + bitmap fonts, verified against the real py-pyrrha test skins.
add_executable(test_skin
    tests/test_skin.cpp
    src/skin/Skin.cpp
    src/skin/BitmapFont.cpp)
target_include_directories(test_skin PRIVATE src)
target_link_libraries(test_skin PRIVATE Qt6::Gui KF6::Archive)
add_test(NAME skin COMMAND test_skin)

# The skinned main window's interaction — synthetic mouse events → signals.
add_executable(test_skinnedwindow
    tests/test_skinnedwindow.cpp
    src/skin/Skin.cpp
    src/skin/BitmapFont.cpp
    src/skin/SkinnedWindow.cpp)
target_include_directories(test_skinnedwindow PRIVATE src)
target_link_libraries(test_skinnedwindow PRIVATE Qt6::Widgets Qt6::Test KF6::Archive)
add_test(NAME skinnedwindow COMMAND test_skinnedwindow)
set_tests_properties(skinnedwindow PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
