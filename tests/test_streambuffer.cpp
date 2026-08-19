// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 the Pyrrha authors
//
// Unit tests for StreamBuffer — the decoder→sink PCM buffer. This is the part of
// the streaming engine that can be validated without audio hardware: read/seek/
// trim/underrun-padding/end-of-stream logic. Actual glitch-free playback through
// QAudioSink still needs a real audio device.
#include <cstdio>
#include <cstring>

#include <QByteArray>

#include "engine/StreamBuffer.h"

using namespace pyrrha;

static int g_failed = 0;
#define CHECK(cond)                                                        \
    do {                                                                   \
        if (!(cond)) {                                                     \
            std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #cond);   \
            ++g_failed;                                                    \
        }                                                                  \
    } while (0)

static void test_keep_all_basic() {
    StreamBuffer sb;
    sb.start(/*seekable=*/true);
    sb.appendPcm("ABCD", 4);
    char b[8];
    CHECK(sb.read(b, 2) == 2);
    CHECK(std::memcmp(b, "AB", 2) == 0);
    CHECK(sb.consumed() == 2);
    CHECK(sb.buffered() == 2);
    CHECK(sb.read(b, 2) == 2);
    CHECK(std::memcmp(b, "CD", 2) == 0);
    CHECK(sb.consumed() == 4);
    CHECK(sb.buffered() == 0);
    CHECK(!sb.atEnd());               // more data may still be coming
    sb.setFinished();
    CHECK(sb.read(b, 2) == 0);        // true end-of-stream
    CHECK(sb.atEnd());
    CHECK(sb.totalWritten() == 4);
}

static void test_underrun_pads_silence() {
    StreamBuffer sb;
    sb.start(true);
    sb.appendPcm("AB", 2);
    char b[4];
    std::memset(b, 0x7f, 4);
    CHECK(sb.read(b, 4) == 4);        // 2 real + 2 silence (not finished)
    CHECK(std::memcmp(b, "AB", 2) == 0);
    CHECK(b[2] == 0 && b[3] == 0);    // padding is silence
    CHECK(sb.consumed() == 2);        // padding must NOT advance the position
}

static void test_all_silence_when_empty() {
    StreamBuffer sb;
    sb.start(true);
    char b[4];
    std::memset(b, 0x7f, 4);
    CHECK(sb.read(b, 4) == 4);        // no data yet, not finished → all silence
    CHECK(b[0] == 0 && b[3] == 0);
    CHECK(sb.consumed() == 0);
    sb.setFinished();
    CHECK(sb.read(b, 4) == 0);        // finished + empty → EOF
}

static void test_seek_keep_all() {
    StreamBuffer sb;
    sb.start(true);
    sb.appendPcm("0123456789", 10);
    char b[16];
    CHECK(sb.read(b, 4) == 4);
    CHECK(std::memcmp(b, "0123", 4) == 0);
    CHECK(sb.seekToByte(1));
    CHECK(sb.consumed() == 1);
    CHECK(sb.read(b, 3) == 3);
    CHECK(std::memcmp(b, "123", 3) == 0);
    CHECK(sb.seekToByte(100));        // clamps to totalWritten (10)
    CHECK(sb.consumed() == 10);
}

static void test_live_trim_preserves_order() {
    StreamBuffer sb;
    sb.start(/*seekable=*/false);     // live: trimming, no seek
    CHECK(!sb.seekToByte(0));         // seek rejected in live mode
    QByteArray in;
    for (int i = 0; i < 300000; ++i)  // well past the 256 KiB trim threshold
        in.append(char((i * 7) & 0xff));
    sb.appendPcm(in.constData(), in.size());
    sb.setFinished();
    QByteArray out;
    char b[4096];
    for (;;) {
        qint64 n = sb.read(b, sizeof(b));
        if (n <= 0)
            break;
        out.append(b, n);
    }
    CHECK(out == in);                 // exact bytes, in order, across many trims
    CHECK(sb.consumed() == in.size());
    CHECK(sb.totalWritten() == in.size());
    CHECK(sb.atEnd());
}

static void test_bytes_available() {
    StreamBuffer sb;
    sb.start(true);
    sb.appendPcm("ABCDE", 5);
    CHECK(sb.bytesAvailable() >= 5);  // unfinished → at least the real bytes
    sb.setFinished();
    char b[8];
    sb.read(b, 5);
    CHECK(sb.bytesAvailable() == 0);  // finished + drained
}

int main() {
    test_keep_all_basic();
    test_underrun_pads_silence();
    test_all_silence_when_empty();
    test_seek_keep_all();
    test_live_trim_preserves_order();
    test_bytes_available();
    if (g_failed == 0)
        std::printf("StreamBuffer: all tests passed\n");
    else
        std::fprintf(stderr, "StreamBuffer: %d check(s) failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
