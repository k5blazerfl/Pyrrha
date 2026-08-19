// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Classic Winamp 2 main-window sprite coordinates (native 275×116, scale 1).
// Transcribed from py-pyrrha's skinned/window.py. These are facts about the skin
// format, not copyrightable expression.
#pragma once

namespace pyrrha::coords {

inline constexpr int kW = 275;
inline constexpr int kH = 116;

// Transport button: destination rect + source column in cbuttons.bmp, with the
// normal / pressed source rows.
struct Button {
    int dx, dy, w, h;   // where it's drawn
    int sx, sy0, sy1;   // cbuttons.bmp source x, normal-y, pressed-y
};
inline constexpr Button kButtons[] = {
    {16, 88, 23, 18, 0, 0, 18},     // prev
    {39, 88, 23, 18, 23, 0, 18},    // play
    {62, 88, 23, 18, 46, 0, 18},    // pause
    {85, 88, 23, 18, 69, 0, 18},    // stop
    {108, 88, 22, 18, 92, 0, 18},   // next
    {136, 89, 22, 16, 114, 0, 16},  // eject
};

// titlebar.bmp: the active bar is blitted from src (27,0), 275×14, to (0,0).
inline constexpr int kTitlebarSrcX = 27;
inline constexpr int kTitlebarActiveY = 0;
inline constexpr int kTitlebarInactiveY = 15;
inline constexpr int kTitlebarW = 275;
inline constexpr int kTitlebarH = 14;

// nums_ex/numbers.bmp time slots (MM:SS) and the leading minus, dest coords.
inline constexpr int kTimeX[4] = {48, 60, 78, 90};
inline constexpr int kTimeY = 26;
inline constexpr int kMinusX = 36;

// text.bmp song-title marquee area.
inline constexpr int kTitleX = 111;
inline constexpr int kTitleY = 27;
inline constexpr int kTitleW = 154;

// volume.bmp background: 68×13 at (107,57), 28 states stacked 15px apart.
inline constexpr int kVolumeX = 107;
inline constexpr int kVolumeY = 57;
inline constexpr int kVolumeW = 68;
inline constexpr int kVolumeH = 13;

// balance.bmp background: 38×13 at (177,57), source x=9.
inline constexpr int kBalanceX = 177;
inline constexpr int kBalanceY = 57;
inline constexpr int kBalanceW = 38;
inline constexpr int kBalanceH = 13;
inline constexpr int kBalanceSrcX = 9;

// posbar.bmp: 248×10 background at (16,72); thumb src (248,0,29,10).
inline constexpr int kPosbarX = 16;
inline constexpr int kPosbarY = 72;
inline constexpr int kPosbarW = 248;
inline constexpr int kPosbarH = 10;
inline constexpr int kPosbarThumbW = 29;

// playpaus.bmp status glyph at (26,28): x=0 play, x=9 pause, 9×9.
inline constexpr int kStatusX = 26;
inline constexpr int kStatusY = 28;

// A hit-testable rectangle.
struct Rect {
    int x, y, w, h;
    constexpr bool contains(int px, int py) const {
        return px >= x && py >= y && px < x + w && py < y + h;
    }
};

// Titlebar buttons (dest rects; glyphs are baked into titlebar.bmp).
inline constexpr Rect kMenuBtn{6, 3, 9, 9};
inline constexpr Rect kMinimizeBtn{244, 3, 9, 9};
inline constexpr Rect kShadeBtn{254, 3, 9, 9};
inline constexpr Rect kCloseBtn{264, 3, 9, 9};

// Slider drag geometry.
inline constexpr int kVolHandleW = 14;
inline constexpr int kBalHandleW = 14;
inline constexpr double kBalSnap = 0.08;   // centre dead-zone
inline constexpr int kTitlebarDragH = 14;  // top strip that moves the window

// Transport button hit-rect (its destination rect).
inline constexpr Rect buttonRect(const Button &b) { return {b.dx, b.dy, b.w, b.h}; }

}  // namespace pyrrha::coords
