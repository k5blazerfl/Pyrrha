# -*- coding: utf-8 -*-
# Pyrrha - a Qt port of Pithos.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 3.

"""Client for the RadioBrowser (https://www.radio-browser.info) directory.

RadioBrowser is a free, community-run, key-less catalogue of internet-radio
streams — the de-facto open API that most modern players use. This is a thin
``urllib`` wrapper matching the Pandora backend's HTTP idiom; every call is
blocking and meant to run on the window's worker thread (via ``worker_run``),
and honours the app's configured HTTP proxy when one is passed.

Functions return plain normalised ``dict``s whose keys line up with
:meth:`pyrrha.radio.RadioStation.from_dict`, so the caller can do
``RadioStation.from_dict(d)`` without any glue.
"""

import json
import logging
import random
import urllib.error
import urllib.parse
import urllib.request

# RadioBrowser asks clients to send a descriptive, non-generic User-Agent so
# server operators can identify traffic.
USER_AGENT = 'Pyrrha (+https://github.com/k5blazerfl/Pyrrha)'

REQUEST_TIMEOUT = 10

# The API is served by a pool of mirrors. We normally discover the live list
# from the round-robin host and pick one at random (RadioBrowser's recommended
# load-spreading); these are a fallback if discovery fails.
_DISCOVERY_URL = 'https://all.api.radio-browser.info/json/servers'
_SERVERS_FALLBACK = (
    'https://de1.api.radio-browser.info',
    'https://de2.api.radio-browser.info',
    'https://nl1.api.radio-browser.info',
    'https://at1.api.radio-browser.info',
)

_server_cache = None    # chosen base URL, resolved once per process


# -- low-level HTTP --------------------------------------------------------

def _opener(proxy):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    return urllib.request.build_opener(*handlers)


def _get_json(url, params=None, proxy=None, timeout=REQUEST_TIMEOUT):
    if params:
        url = url + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with _opener(proxy).open(req, timeout=timeout) as resp:
        return json.loads(resp.read())          # json.loads accepts bytes (3.6+)


def _base(proxy=None):
    """The base URL of a live API mirror, discovered once and cached."""
    global _server_cache
    if _server_cache:
        return _server_cache
    try:
        servers = _get_json(_DISCOVERY_URL, proxy=proxy, timeout=8)
        hosts = [s['name'] for s in servers if isinstance(s, dict) and s.get('name')]
        if hosts:
            _server_cache = 'https://' + random.choice(hosts)
            return _server_cache
    except (urllib.error.URLError, ValueError, OSError) as e:
        logging.info('RadioBrowser server discovery failed: %s', e)
    _server_cache = random.choice(_SERVERS_FALLBACK)
    return _server_cache


def _normalize(d):
    """Map a raw RadioBrowser station record to RadioStation.from_dict keys.
    Prefers ``url_resolved`` (already followed any playlist redirect)."""
    return {
        'name': (d.get('name') or '').strip(),
        'url': d.get('url_resolved') or d.get('url') or '',
        'uuid': d.get('stationuuid'),
        'favicon': d.get('favicon') or '',
        'tags': d.get('tags') or '',
        'codec': d.get('codec') or '',
        'bitrate': d.get('bitrate') or 0,
        'homepage': d.get('homepage') or '',
        'country': d.get('countrycode') or d.get('country') or '',
    }


# -- public API ------------------------------------------------------------

def search(query='', tag='', countrycode='', order='clickcount',
           reverse=True, limit=100, hidebroken=True, proxy=None):
    """Search stations by (any of) name, tag, and country code. Returns a list
    of normalised station dicts, most-popular first by default."""
    params = {
        'limit': int(limit),
        'order': order,
        'reverse': 'true' if reverse else 'false',
        'hidebroken': 'true' if hidebroken else 'false',
    }
    if query:
        params['name'] = query
    if tag:
        params['tagList'] = tag
    if countrycode:
        params['countrycode'] = countrycode
    data = _get_json(_base(proxy) + '/json/stations/search', params, proxy=proxy)
    return [_normalize(d) for d in data if (d.get('url_resolved') or d.get('url'))]


def top_stations(limit=100, proxy=None):
    """The most-clicked stations overall (a sensible default landing list)."""
    data = _get_json(_base(proxy) + '/json/stations/topclick/%d' % int(limit),
                     proxy=proxy)
    return [_normalize(d) for d in data if (d.get('url_resolved') or d.get('url'))]


def tags(limit=100, proxy=None):
    """Popular genre/tag names, most-used first (for a filter dropdown)."""
    params = {'order': 'stationcount', 'reverse': 'true', 'limit': int(limit),
              'hidebroken': 'true'}
    data = _get_json(_base(proxy) + '/json/tags', params, proxy=proxy)
    return [t.get('name') for t in data if isinstance(t, dict) and t.get('name')]


def countries(proxy=None):
    """Countries present in the catalogue as ``{'name', 'code'}`` dicts."""
    params = {'order': 'name', 'hidebroken': 'true'}
    data = _get_json(_base(proxy) + '/json/countries', params, proxy=proxy)
    return [{'name': c.get('name', ''), 'code': c.get('iso_3166_1', '')}
            for c in data if isinstance(c, dict) and c.get('iso_3166_1')]


def fetch_image(url, proxy=None, timeout=8, max_bytes=512 * 1024):
    """Fetch a station logo (favicon) as raw bytes, capped at ``max_bytes``.
    Blocking — run on a worker thread. Raises on network error."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with _opener(proxy).open(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def click(stationuuid, proxy=None):
    """Register a listen with RadioBrowser (feeds its popularity ranking).
    Best-effort — failures are logged and swallowed."""
    if not stationuuid:
        return
    try:
        _get_json(_base(proxy) + '/json/url/' + urllib.parse.quote(stationuuid),
                  proxy=proxy, timeout=6)
    except (urllib.error.URLError, ValueError, OSError) as e:
        logging.info('RadioBrowser click registration failed: %s', e)
