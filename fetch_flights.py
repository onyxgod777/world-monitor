#!/usr/bin/env python3
"""fetch_flights.py — live aircraft positions into flights.js for the world map.

Source: adsb.lol, a community ADS-B network that offers its API keyless. It is polled
at a set of regional centres covering the world's busiest airspace and the results are
deduplicated by ICAO hex.

IMPORTANT — why this is a snapshot and not a live radar: no free ADS-B API returns
CORS headers, so a browser cannot call one directly. adsb.lol and adsb.fi answer a
preflight with 405, OpenSky allows only its own origin, and airplanes.live requires a
Whitelisting email. Rather than route this dashboard through a third-party CORS proxy
(an unreliable dependency that would also make us someone else's traffic), positions
are snapshotted and the panel is labelled with the time they were taken. Aircraft move
at ~800 km/h, so the age of the snapshot matters and is always displayed.

Policy: adsb.lol asks for at most one request per second and a descriptive
User-Agent; both are respected below.

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
UA = {'User-Agent': 'WorldMonitor/1.0 (+https://worldmonitor.thealpha-secret.xyz; '
                    'contact sunntzu@realvalueofpi.xyz)',
      'Accept': 'application/json'}

# Regional centres covering the busiest airspace. 250 nm is the API's maximum radius.
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

RADIUS = 250        # nautical miles, the API maximum
MAX_AIRCRAFT = 3000


def fetch_centre(lat, lon, tries=3):
    """Fetch one centre, backing off on 429 — adsb.lol rate-limits bursts."""
    url = 'https://api.adsb.lol/v2/point/%s/%s/%d' % (lat, lon, RADIUS)
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode('utf-8', 'replace')).get('ac', []) or []
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429 and attempt < tries - 1:
                wait = 8 * (attempt + 1)
                print('        429 — waiting %ds and retrying' % wait)
                time.sleep(wait)
                continue
            raise
        except Exception as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(4)
                continue
            raise
    raise last if last else RuntimeError('unreachable')


def main():
    seen, batches, per_centre = set(), [], []
    for name, lat, lon in CENTRES:
        try:
            batch = fetch_centre(lat, lon)
        except Exception as exc:
            print('  %-13s failed: %s' % (name, exc))
            per_centre.append((name, 0))
            time.sleep(2.0)
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
            track = a.get('track')
            gs = a.get('gs')
            mil = bool((a.get('dbFlags') or 0) & 1)
            kept.append([
                round(alat, 3), round(alon, 3),
                round(track, 0) if isinstance(track, (int, float)) else 0,
                int(alt) if isinstance(alt, (int, float)) else -1,
                int(gs) if isinstance(gs, (int, float)) else 0,
                (a.get('flight') or '').strip() or (a.get('r') or ''),
                (a.get('t') or '').strip(),
                1 if mil else 0,
            ])
        batches.append((name, kept))
        per_centre.append((name, len(kept)))
        print('  %-13s %4d aircraft' % (name, len(kept)))
        time.sleep(2.0)                      # adsb.lol asks for <= 1 request/second

    # Interleave the centres rather than concatenating them: with a cap in place,
    # concatenation would silently starve whichever regions were polled last.
    aircraft, i = [], 0
    while len(aircraft) < MAX_AIRCRAFT and any(len(k) > i for _, k in batches):
        for _, k in batches:
            if i < len(k):
                aircraft.append(k[i])
                if len(aircraft) >= MAX_AIRCRAFT:
                    break
        i += 1

    if len(aircraft) < 50:
        print('only %d aircraft parsed — aborting so as not to clobber flights.js' % len(aircraft))
        return 2

    covered = sum(1 for _, n in per_centre if n > 0)
    empty = [n for n, c in per_centre if c == 0]

    # a same-minute signature, so an unchanged sky does not spam git
    sig = json.dumps(sorted(a[0] for a in aircraft))[:20000]
    prev_sig = ''
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
            prev_sig = json.dumps(sorted(str(a[0]) for a in prev.get('ac', [])))[:20000]
        except Exception:
            prev_sig = ''

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'source': 'adsb.lol',
        'note': 'Snapshot of live aircraft positions. Not real-time: see _updated.',
        'centres': len(CENTRES),
        'centres_covered': covered,
        'centres_empty': empty,
        'radius_nm': RADIUS,
        'count': len(aircraft),
        'military': sum(1 for a in aircraft if a[7]),
        # [lat, lon, track, altitude_ft (-1 unknown), groundspeed_kt, callsign, type, mil]
        'ac': aircraft,
    }
    content = ('// AUTO-GENERATED by fetch_flights.py — do not edit by hand.\n'
               '// Live aircraft positions sampled from the adsb.lol community network at\n'
               '// regional centres worldwide. A SNAPSHOT, not a real-time feed: no free\n'
               '// ADS-B API returns CORS headers, so a browser cannot poll one directly.\n'
               '// ac rows: [lat, lon, track, alt_ft (-1 unknown), groundspeed_kt, callsign, type, mil]\n'
               'window.FLIGHTS = ' + json.dumps(data, ensure_ascii=False) + ';\n')
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote flights.js: %d aircraft from %d centres (%d military), %d KB'
          % (len(aircraft), len(CENTRES), data['military'], len(content) // 1024))

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
