# Pandora support — plugin build spec

Pandora comes back as a **separate, GPLv3, optional plugin** — a `SourceProvider`
that yields tracks whose `audioUrl` the shared `QtAudioEngine` plays (Pandora
streams are AAC/MP3 over HTTPS, so the core engine needs no Pandora-specific
code). Nothing here lives in the GPL-2.0-or-later core.

Source of truth for the protocol: py-pyrrha's vendored Pithos client
(`~/py-pyrrha/pyrrha/pandora/*`, `keyring.py`, and its use in `window.py`).

## Licensing (decides what we may reuse)

- `pandora/pandora.py`, `data.py`, `fake.py`, `keyring.py` — **GPLv3** (Pithos /
  Kevin Mehall, Christopher Eby). The plugin is a derivative of this protocol
  logic → **the plugin is GPLv3**, in its own package/repo. The core stays
  GPL-2.0-or-later; a GPL-2-or-later core may combine with a GPLv3 plugin the
  user installs.
- `pandora/blowfish.py` — **AGPLv3** (Versile). **Do NOT port or vendor it.** The
  Blowfish *algorithm* is public-domain; only Versile's *code* is AGPL.
  Reimplement with **OpenSSL EVP** `BF-ECB`.

## Dependencies (all verified present on this system)

| Need | Provided by | Status |
|---|---|---|
| Blowfish ECB | OpenSSL 3.6 `EVP_CIPHER_fetch("BF-ECB")` | ✓ available in the default *and* legacy providers (`OSSL_PROVIDER_load("legacy")` as a portability guard) |
| HTTP/JSON client | `Qt6::Network` (`QNetworkAccessManager`, `QJsonDocument`) | ✓ |
| Credential store | `Qt6Keychain` (or HeDE's own Secret Service) | ✓ installed |
| pandora-one TLS | pin `data.py`'s `internal_cert` PEM into `QSslConfiguration` CA set | data present |

## Protocol flow (one path: `PandoraClient::jsonCall(method,args,https,blowfish)`)

Session state threaded through every call: `partnerId`, `partnerAuthToken`,
`userId`, `userAuthToken`, `timeOffset` (server−local seconds).

1. **`auth.partnerLogin`** — TLS, **plaintext body** (`blowfish=false`). Body =
   partner client dict `{deviceModel, username, password, version}`. → save
   `partnerId`, `partnerAuthToken`.
2. **syncTime offset** — the response's `syncTime` is Blowfish-encrypted:
   `pandora_decrypt(syncTime)` → **drop the first 4 bytes**, take the next 10
   ASCII digits as a Unix time → `timeOffset = serverTime − localTime`.
3. **`auth.userLogin`** — TLS, encrypted. Body `{username:<email>, password,
   loginType:"user", returnIsSubscriber:true}` + injected `partnerAuthToken`,
   `syncTime`. → save `userId`, `userAuthToken`, `isSubscriber`.
4. **`user.getStationList`** `{returnAllStations:true}` (http, encrypted).
5. **`station.getPlaylist`** — TLS, encrypted, `{stationToken,
   includeTrackLength:true, additionalAudioUrl:"HTTP_32_AACPLUS,HTTP_128_MP3"}`
   → `items[]` (~4 tracks).
6. **Play** a track's `audioUrlMap[quality].audioUrl`.

Every authenticated call injects `syncTime = now + timeOffset` and the
appropriate `userAuthToken`/`partnerAuthToken` into the body.

## Encryption (Blowfish ECB, hex)

Two keyed ciphers per session (encrypt key ≠ decrypt key, from the partner dict).

- **Encrypt request body**: UTF-8 JSON → **NUL-pad to a multiple of 8** (not
  PKCS) → Blowfish-ECB encrypt (`EVP_bf_ecb`, `set_padding(0)`) → **lowercase
  hex**. That hex string is the POST body.
- **Decrypt** (only ever the `syncTime` field): hex-decode → Blowfish-ECB
  decrypt → strip trailing `0x08`.
- `auth.partnerLogin` is the *only* unencrypted call; **responses are always
  plaintext JSON**.

Verify our OpenSSL implementation byte-for-byte against Pithos with the partner
keys before trusting it (the P/S constants in blowfish.py are the standard ones,
so OpenSSL agrees).

## Endpoints / methods

- Base: `http[s]://tuner.pandora.com/services/json/?...` (android) or
  `internal-tuner.pandora.com` (pandora-one). Per-call TLS flag matters — the
  server enforces it: partnerLogin/userLogin/getPlaylist use HTTPS; most others
  (getStationList, addFeedback, search, station CRUD) use plain HTTP.
- Query args (only non-null): `partner_id`, `user_id`, `auth_token`
  (percent-encoded; user token preferred, else partner), `method`.
- Headers: `User-Agent: pithos`, `Content-Type: text/plain`, POST.
- Methods: `auth.partnerLogin`, `auth.userLogin`, `user.getStationList`,
  `user.setQuickMix`, `user.getSettings`, `user.setExplicitContentFilter`,
  `user.sleepSong`, `station.getPlaylist`, `station.createStation`,
  `station.deleteStation`, `station.renameStation`,
  `station.transformSharedStation` (before rating a shared station),
  `station.addFeedback` (→ `feedbackId`), `station.deleteFeedback`,
  `music.search`, `bookmark.addSongBookmark`, `bookmark.addArtistBookmark`.
- Response envelope `{"stat":"ok","result":{…}}` / `{"stat":"fail","code":N}`.
  Handle `1001 INVALID_AUTH_TOKEN` → re-login + retry once.

## Partner keys (`data.py`)

- **android-generic** (default): deviceModel `android-generic`, user `android`,
  pass `AC7IBG09A3DTSYM4R41UJWL07VLN8JI7`, encryptKey `6#26FRL$ZWD`, decryptKey
  `R=U!LH$O2B#`, version `5`, host `tuner.pandora.com`.
- **pandora-one** (subscribers): deviceModel `D01`, user `pandora one`, pass
  `TVCKIBGS9AO9TSYLNNFUML0743LH82D`, encryptKey `2%3WCL*JU$MP]4`, decryptKey
  `U#IO$RZPAB%VX2`, host `internal-tuner.pandora.com` (pinned cert). Pick by the
  `pandora-one` setting; after login reconcile against `isSubscriber` and
  reconnect if they disagree.

## Audio & tracks

- A song carries `audioUrlMap[quality]={encoding,bitrate,audioUrl}` +
  `additionalAudioUrl`. Post-process exactly as pandora.py:484-499 to build the
  quality tiers per subscriber status. A Pandora `Track` is just the resolved
  `audioUrl` (string) + metadata (`songName`, `artistName`, `albumName`,
  `albumArtUrl`, `trackToken`, `songRating`, `trackLength`, `trackGain`).
- **Stream URLs expire ~1h** (`PLAYLIST_VALIDITY_TIME=3600`) — refetch, never
  cache indefinitely; top the queue up when it runs low.
- **No ads**: drop playlist items lacking a `songName` key. Do not implement ad
  fetching.

## Credentials

py-pyrrha used libsecret with schema `io.github.k5blazerfl.Pyrrha.Account`
(attribute `email`), email itself stored in settings, password in the keyring.
Port to **Qt6Keychain** (`ReadPasswordJob`/`WritePasswordJob`) or HeDE's own
Secret Service; key = account email, email persisted in `QSettings`.

## Port shape (C++/Qt6, pure — no GLib)

- **`PandoraCrypto`** — OpenSSL EVP wrapper: `encrypt(json)→hex`,
  `decryptSyncTime(hex)→bytes`. Loads the `legacy` provider defensively.
- **`PandoraClient : QObject`** — 1:1 with `Pandora`: `jsonCall`, `connect`
  (partnerLogin→syncTime→userLogin), `getStations`, feedback/search/CRUD.
  `QNetworkAccessManager` + `QJsonDocument`, all async (callbacks), pins the
  pandora-one cert.
- **`PandoraStation`** (id/token/name/flags; getPlaylist/rename/delete/transform)
  and **`PandoraTrack`** (audioUrl-by-quality, rate via add/deleteFeedback with
  the shared-station transform, tired, bookmark; state save/restore).
- **`PandoraSource : SourceProvider`** — the plugin: owns a `PandoraClient`, the
  station list, yields `PandoraTrack`s; advertises Pandora-only capabilities
  (love/ban/unrate, bookmarks).
- **`FakePandoraClient`** (port `fake.py`) — a `--test` mode returning canned
  stations + a public AAC test file, no network/crypto; good for CI of the
  engine without credentials.

## Plugin mechanics (to design)

The core needs a plugin discovery/loading slot (`QPluginLoader` + a
`SourceProviderPlugin` interface) so `pyrrha-pandora` (a separate GPLv3 package,
its own repo/ebuild) drops in without the core depending on it. This is the one
new piece of core infrastructure Pandora needs; everything else lives in the
plugin.
