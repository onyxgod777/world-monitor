#!/usr/bin/env python3
"""fetch_flights.py — aircraft positions into flights.js for the world map.

WHY THIS CHANGED (2026-10-20)
-----------------------------
This used to poll adsb.lol at 48 regional centres, one request per centre — slow
and eventually fatal:

  * 48 sequential requests with a 2 s politeness sleep is ~96 s of pure waiting
    per run, and one slow or rate-limited centre could add 45 s x 3 tries on top.
    Runs were measured at 5-60 minutes (one had to be killed at 12).
  * adsb.lol's quota is `500, 4;w=1, 60;w=60, 500;w=86400` — a HARD 500 requests
    per day per IP. 48 requests per run cannot live inside that at any useful
    cadence (48 x 24 = 1152/day), so the IP was 429-walled with
    `x-ratelimit-reset: 20748` (~5.8 h) and later runs just spun on retries.

Primary source is now OpenSky's `/api/states/all`: ONE keyless request returns
every aircraft currently tracked worldwide (~12.7k rows, ~1.7 MB, ~1.5 s). One
request per run at a 30-minute cadence is 48/day — no quota to blow, and the run
finishes in seconds.

adsb.lol survives as the FALLBACK fan-out and for one enrichment: `/v2/mil`,
because OpenSky does not report military aircraft. Every adsb.lol call spends
from a persisted daily budget, so this file cannot rate-limit itself into a ban
again.

IMPORTANT — why this is a snapshot and not a live radar: no free ADS-B API
returns CORS headers, so a browser cannot call one directly (adsb.lol and adsb.fi
answer a preflight with 405, OpenSky allows only its own origin, airplanes.live
wants a whitelisting email). Rather than route the dashboard through a
third-party CORS proxy, positions are snapshotted and the panel is labelled with
the time they were taken. Aircraft move at ~800 km/h, so that age is displayed.

Policy: adsb.lol asks for at most one request per second and a descriptive
User-Agent; OpenSky asks for a descriptive User-Agent. Both are respected.

Usage:
    python3 fetch_flights.py            # write flights.js
    python3 fetch_flights.py --commit   # write, then commit + push if changed
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get('WM_REPO_DIR', os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'flights.js')
STATE = os.environ.get('WM_STATE_DIR') or os.path.expanduser('~/.hermes/state')
BUDGET_FILE = os.path.join(STATE, 'adsb_requests.json')

UA = {'User-Agent': 'WorldMonitor/1.0 (+https://worldmonitor.thealpha-secret.xyz; '
                    'contact sunntzu@realvalueofpi.xyz)',
      'Accept': 'application/json'}

# Regional centres covering the busiest airspace — FALLBACK ONLY now. 250 nm is
# the adsb.lol maximum radius. Ordered busiest-first, so a budget-limited
# fallback still spends its few requests where the traffic is.
CENTRES = [
    ('London',      51.47,   -0.45), ('Paris',        49.01,    2.55),
    ('Frankfurt',   50.03,    8.56), ('Amsterdam',    52.31,    4.76),
    ('Madrid',      40.47,   -3.56), ('Rome',         41.80,   12.25),
    ('Istanbul',    41.28,   28.75), ('Moscow',       55.41,   37.90),
    ('Dubai',       25.25,   55.36), ('Doha',         25.27,   51.61),
    ('Delhi',       28.56,   77.10), ('Mumbai',       19.09,   72.87),
    ('Singapore',    1.36,  103.99), ('Bangkok',      13.69,  100.75),
    ('Hong Kong',   22.31,  113.91), ('Shanghai',     31.14,  121.80),
    ('Beijing',     40.08,  116.58), ('Tokyo',        35.55,  139.78),
    ('Seoul',       37.46,  126.44), ('Taipei',       25.08,  121.23),
    ('Sydney',     -33.94,  151.18), ('Melbourne',   -37.67,  144.84),
    ('Auckland',   -37.01,  174.79), ('Jakarta',      -6.13,  106.66),
    ('Manila',      14.51,  121.02), ('Los Angeles',  33.94, -118.40),
    ('New York',    40.64,  -73.78), ('Chicago',      41.98,  -87.90),
    ('Dallas',      32.90,  -97.04), ('Atlanta',      33.64,  -84.43),
    ('Miami',       25.79,  -80.29), ('Denver',       39.86, -104.67),
    ('Seattle',     47.45, -122.31), ('Toronto',      43.68,  -79.63),
    ('Mexico City', 19.44,  -99.07), ('Sao Paulo',   -23.43,  -46.47),
    ('Bogota',       4.70,  -74.15), ('Buenos Aires',-34.82,  -58.54),
    ('Lima',       -12.02,  -77.11), ('Johannesburg',-26.13,   28.24),
    ('Nairobi',     -1.32,   36.93), ('Cairo',        30.11,   31.41),
    ('Lagos',        6.58,    3.32), ('Casablanca',   33.37,   -7.59),
    ('Anchorage',   61.17, -149.99), ('Reykjavik',    63.99,  -22.62),
    ('Honolulu',    21.32, -157.92), ('Tahiti',      -17.55, -149.61),
]

RADIUS = 250             # nautical miles, the adsb.lol API maximum
MAX_AIRCRAFT = 3000      # row cap; sampled geographically, see sample_rows()
ADSB_DAILY_BUDGET = 450  # of adsb.lol's advertised 500/day — keep headroom
FALLBACK_SECONDS = 240   # hard wall-clock budget for the per-centre fallback
M_PER_FT = 3.280839895
MS_TO_KT = 1.943844


# ── adsb.lol request budget ──────────────────────────────────────────────────
def _budget_load():
    """{'day': 'YYYY-MM-DD', 'used': n} — resets when the UTC day rolls over."""
    today = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    try:
        with open(BUDGET_FILE, encoding='utf-8') as f:
            b = json.load(f)
        if b.get('day') == today:
            return {'day': today, 'used': int(b.get('used') or 0)}
    except Exception:
        pass
    return {'day': today, 'used': 0}


def _budget_save(b):
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(BUDGET_FILE, 'w', encoding='utf-8') as f:
            json.dump(b, f)
    except Exception:
        pass


def budget_left():
    return max(0, ADSB_DAILY_BUDGET - _budget_load()['used'])


def budget_spend(n=1):
    """Spend n adsb.lol requests; False when today's budget cannot cover it."""
    b = _budget_load()
    if b['used'] + n > ADSB_DAILY_BUDGET:
        return False
    b['used'] += n
    _budget_save(b)
    return True


def _get_json(url, timeout):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


# ── primary source: OpenSky, one request for the whole world ─────────────────
def fetch_opensky():
    """One keyless request -> every aircraft OpenSky tracks, worldwide.

    states/all row: [icao24, callsign, origin_country, time_position,
                     last_contact, lon, lat, baro_altitude_m, on_ground,
                     velocity_ms, true_track, vertical_rate, sensors,
                     geo_altitude_m, squawk, spi, source]
    """
    data = _get_json('https://opensky-network.org/api/states/all', timeout=60)
    rows = []
    for s in data.get('states') or []:
        try:
            if len(s) < 11:
                continue
            lon, lat = s[5], s[6]
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            on_ground = bool(s[8])
            alt_m = s[7]
            alt_ft = 0 if on_ground else (
                int(round(alt_m * M_PER_FT)) if isinstance(alt_m, (int, float)) else -1)
            track, vel = s[10], s[9]
            rows.append([
                round(lat, 3), round(lon, 3),
                round(track, 0) if isinstance(track, (int, float)) else 0,
                alt_ft,
                int(round(vel * MS_TO_KT)) if isinstance(vel, (int, float)) else 0,
                (s[1] or '').strip(),
                '',                      # OpenSky states/all has no aircraft type
                0,                       # military flag: filled by enrich_military()
                str(s[0] or '').lower(),  # icao24 hex
            ])
        except Exception:
            continue                 # one malformed row must not kill the pass
    return rows


# ── fallback: adsb.lol per-centre fan-out, budget- and time-boxed ────────────
def fetch_adsb_centre(lat, lon, timeout=12):
    url = 'https://api.adsb.lol/v2/point/%s/%s/%d' % (lat, lon, RADIUS)
    for attempt in range(2):
        try:
            return _get_json(url, timeout=timeout).get('ac') or []
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                # Do NOT retry-loop: the quota is per-DAY, so hammering it burns
                # the run's wall clock for nothing. Give up on adsb.lol instead.
                raise
            if attempt == 0:
                time.sleep(3)
                continue
            raise
        except Exception:
            if attempt == 0:
                time.sleep(3)
                continue
            raise
    return []


def fetch_adsb_fallback():
    """Per-centre fan-out, stopping when the time box or the request budget ends."""
    started = time.time()
    seen, batches, used, empty = set(), [], 0, []
    for name, lat, lon in CENTRES:
        if time.time() - started > FALLBACK_SECONDS:
            print('  fallback: %.0fs time box reached after %d centres'
                  % (FALLBACK_SECONDS, used))
            break
        if not budget_spend(1):
            print('  fallback: adsb.lol daily budget spent (%d) — stopping' % ADSB_DAILY_BUDGET)
            break
        used += 1
        try:
            batch = fetch_adsb_centre(lat, lon)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                reset = exc.headers.get('x-ratelimit-reset') if exc.headers else '?'
                print('  fallback: adsb.lol rate-limited (resets in %ss) — stopping' % reset)
                break
            print('  %-13s failed: %s' % (name, exc))
            empty.append(name)
            continue
        except Exception as exc:
            print('  %-13s failed: %s' % (name, exc))
            empty.append(name)
            continue
        kept = []
        for a in batch:
            hexid = (a.get('hex') or '').lower()
            alat, alon = a.get('lat'), a.get('lon')
            if not hexid or hexid in seen or not isinstance(alat, (int, float)) \
               or not isinstance(alon, (int, float)):
                continue
            seen.add(hexid)
            alt = a.get('alt_baro')
            if alt == 'ground':
                alt = 0
            if not isinstance(alt, (int, float)):
                alt = None
            track, gs = a.get('track'), a.get('gs')
            mil = bool((a.get('dbFlags') or 0) & 1)
            kept.append([
                round(alat, 3), round(alon, 3),
                round(track, 0) if isinstance(track, (int, float)) else 0,
                int(alt) if isinstance(alt, (int, float)) else -1,
                int(gs) if isinstance(gs, (int, float)) else 0,
                (a.get('flight') or '').strip() or (a.get('r') or ''),
                (a.get('t') or '').strip(),
                1 if mil else 0,
                hexid,
            ])
        batches.append(kept)
        print('  %-13s %4d aircraft' % (name, len(kept)))
        time.sleep(1.1)              # adsb.lol asks for <= 1 request/second
    rows = []
    for b in batches:
        rows.extend(b)
    return rows, used, empty


def enrich_military(rows):
    """Flag military aircraft via adsb.lol /v2/mil — OpenSky does not report it.

    One request when the budget allows, entirely best-effort: a 429, an outage
    or a spent budget leaves every mil flag at 0, which is what the panel shows
    today anyway.
    """
    if os.environ.get('WM_NO_MIL'):
        return 0
    if not budget_spend(1):
        return 0
    try:
        data = _get_json('https://api.adsb.lol/v2/mil', timeout=20)
    except Exception as exc:
        print('  military enrichment skipped: %s' % exc)
        return 0
    mil_hexes = {(a.get('hex') or '').lower() for a in (data.get('ac') or [])} - {''}
    hit = 0
    for r in rows:
        if len(r) > 8 and r[8] in mil_hexes:
            r[7] = 1
            hit += 1
    print('  military enrichment: %d hexes tracked, %d matched' % (len(mil_hexes), hit))
    return hit


# ── shared ───────────────────────────────────────────────────────────────────
def sample_rows(rows, cap=MAX_AIRCRAFT):
    """Cap the row count without starving whole regions.

    The old code interleaved centres so a cap could not quietly drop the last
    continents polled. With one worldwide source there are no centres, so bucket
    by a coarse lat/lon grid and round-robin the buckets — same guarantee.
    """
    if len(rows) <= cap:
        return rows
    buckets = {}
    for r in rows:
        buckets.setdefault((int(r[0] // 15), int(r[1] // 15)), []).append(r)
    picked, i = [], 0
    keys = list(buckets)
    while len(picked) < cap:
        progressed = False
        for k in keys:
            b = buckets[k]
            if i < len(b):
                picked.append(b[i])
                progressed = True
                if len(picked) >= cap:
                    break
        if not progressed:
            break
        i += 1
    return picked


def main():
    started = time.time()
    source, note = 'opensky', 'OpenSky Network — one worldwide states/all request'
    rows, fallback_used, fallback_empty = [], 0, []

    try:
        rows = fetch_opensky()
        print('opensky: %d aircraft with a position in %.1fs' % (len(rows), time.time() - started))
    except Exception as exc:
        print('opensky failed: %s' % exc)
        rows = []

    if len(rows) < 50:
        print('falling back to the adsb.lol per-centre fan-out')
        try:
            rows, fallback_used, fallback_empty = fetch_adsb_fallback()
            source = 'adsb.lol'
            note = ('Snapshot sampled from the adsb.lol community network at %d '
                    'regional centres' % fallback_used)
        except Exception as exc:
            print('adsb.lol fallback failed: %s' % exc)
            rows = []

    if len(rows) < 50:
        print('only %d aircraft parsed — aborting so as not to clobber flights.js' % len(rows))
        return 2

    # dedupe by hex (OpenSky is already unique; the fallback may not be)
    seen, uniq = set(), []
    for r in rows:
        h = r[8] if len(r) > 8 else ''
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        uniq.append(r)
    rows = sample_rows(uniq)

    mil = enrich_military(rows)

    # Change detection: a repainted sky is a commit, a fresh stamp alone is not.
    def sigify(items):
        return ','.join(sorted(
            (a[8] if len(a) > 8 and a[8] else '%s,%s' % (a[0], a[1])) for a in items))

    sig = sigify(rows)
    prev_sig = ''
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
            prev_sig = sigify(prev.get('ac', []))
        except Exception:
            prev_sig = ''

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'source': source,
        'note': 'Snapshot of aircraft positions. Not real-time: see _updated.',
        'method': note,
        'count': len(rows),
        'military': mil or sum(1 for r in rows if r[7]),
        # [lat, lon, track, alt_ft (-1 unknown), groundspeed_kt, callsign, type, mil, hex]
        'ac': rows,
    }
    if source == 'adsb.lol':
        data['centres'] = fallback_used
        data['centres_empty'] = fallback_empty
        data['radius_nm'] = RADIUS

    if sig == prev_sig:
        print('flights.js unchanged (%d aircraft, %s) — not rewriting' % (len(rows), stamp))
        return 0

    content = ('// AUTO-GENERATED by fetch_flights.py — do not edit by hand.\n'
               '// Aircraft positions from '
               + ('OpenSky (one worldwide request)' if source == 'opensky'
                  else 'the adsb.lol community network') + '.\n'
               '// A SNAPSHOT, not a real-time feed: no free ADS-B API returns CORS\n'
               '// headers, so a browser cannot poll one directly.\n'
               '// ac rows: [lat, lon, track, alt_ft (-1 unknown), groundspeed_kt, callsign, type, mil, hex]\n'
               'window.FLIGHTS = ' + json.dumps(data, ensure_ascii=False) + ';\n')
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote flights.js: %d aircraft, %d military, %d KB, total %.1fs'
          % (len(rows), data['military'], len(content) // 1024, time.time() - started))

    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'flights.js'], check=True)
        try:
            subprocess.run(['git', '-C', REPO, 'commit', '-m',
                            'flights: aircraft snapshot %s' % stamp[:16]], check=True)
            subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
            print('committed + pushed')
        except subprocess.CalledProcessError as exc:
            print('git step failed (%s)' % exc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
