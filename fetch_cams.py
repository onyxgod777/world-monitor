#!/usr/bin/env python3
"""fetch_cams.py — build cams.js from owner-published public CCTV cameras.

Source: Caltrans CWWP2 (Commercial Wholesale Web Portal). Their own page states the
data is free of charge and published in JSON "for integration into your application" —
so this is a source that WANTS to be used programmatically, unlike camera-scraping
directories or Shodan results of misconfigured private devices.

Two kinds of feed per camera:
  * static  - a JPEG refreshed every 1-5 minutes (cheap; the browser re-pulls it)
  * streaming - an HLS .m3u8 playlist (~400 kbps) for real live video

Every camera written to cams.js is verified with a real request first: if the image
does not come back as an image, the camera is dropped. The panel must never advertise
a camera that does not work.

Usage:
    python3 fetch_cams.py            # write cams.js
    python3 fetch_cams.py --commit   # write, then git commit + push if changed
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.environ.get('WM_REPO_DIR', os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'cams.js')
UA = {'User-Agent': 'WorldMonitor-Cams/1.0 (https://worldmonitor.thealpha-secret.xyz; '
                    'contact sunntzu@realvalueofpi.xyz)'}

# A spread of districts so the panel is not one city.
DISTRICTS = [('3', 'Sacramento'), ('4', 'Bay Area'), ('7', 'Los Angeles'),
             ('8', 'Inland Empire'), ('11', 'San Diego')]
WANT = 12          # cameras to publish
MAX_VERIFY = 40    # cap on image checks per run


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def verify_image(url):
    """True only if the URL really returns image bytes right now."""
    try:
        req = urllib.request.Request(url, headers=dict(UA, Range='bytes=0-2047'))
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(16)
            ctype = r.headers.get('Content-Type', '')
        if not head:
            return False
        is_jpeg = head[:2] == b'\xff\xd8'
        is_png = head[:8] == b'\x89PNG\r\n\x1a\n'
        return (is_jpeg or is_png) and 'image' in ctype.lower()
    except Exception:
        return False


def verify_stream(url):
    """True only if the URL really serves a playable HLS playlist right now.

    A 200 is not enough: some endpoints answer with an HTML error page or an empty
    manifest. Require a real #EXTM3U header and, when the master playlist lists a
    variant, follow it once to confirm the stream actually has segments.
    """
    if not url:
        return False, ''
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status != 200:
                return False, ''
            body = r.read(4096).decode('utf-8', 'replace')
        if not body.lstrip().startswith('#EXTM3U'):
            return False, ''
        variant = ''
        for line in body.splitlines():
            t = line.strip()
            if t and not t.startswith('#'):
                variant = t
                break
        if not variant:
            return False, ''
        base = url.rsplit('/', 1)[0]
        vurl = variant if variant.startswith('http') else base + '/' + variant
        with urllib.request.urlopen(urllib.request.Request(vurl, headers=UA), timeout=30) as vr:
            vbody = vr.read(4096).decode('utf-8', 'replace')
        if '#EXTINF' not in vbody and '#EXT-X-BYTERANGE' not in vbody:
            return False, ''
        m = re.search(r'RESOLUTION=(\d+x\d+)', body)
        return True, (m.group(1) if m else '')
    except Exception:
        return False, ''


def cameras_from(district_id):
    url = 'https://cwwp2.dot.ca.gov/data/d%s/cctv/cctvStatusD0%s.json' % (district_id, district_id)
    doc = json.loads(get(url).decode('utf-8', 'replace'))
    node = doc.get('data', [])
    # the document is data -> [ {cctv: {one camera}}, ... ] (D3 returns 275 wrappers),
    # but a single-camera file can also arrive as one bare object. Flatten all shapes.
    items = node if isinstance(node, list) else [node]
    cams = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inner = item.get('cctv')
        if isinstance(inner, dict):
            cams.append(inner)
        elif isinstance(inner, list):
            cams.extend(x for x in inner if isinstance(x, dict))
        else:
            cams.append(item)
    out = []
    for c in cams:
        loc = c.get('location') or {}
        img = ((c.get('imageData') or {}).get('static') or {}).get('currentImageURL') or ''
        stream = (c.get('imageData') or {}).get('streamingVideoURL') or ''
        name = (loc.get('locationName') or '').strip()
        if str(c.get('inService', '')).lower() != 'true' or not name or not img.startswith('http'):
            continue
        out.append({
            'name': name,
            'route': loc.get('route', ''),
            'place': loc.get('nearbyPlace', ''),
            'county': loc.get('county', ''),
            'district': district_id,
            'lat': loc.get('latitude', ''),
            'lon': loc.get('longitude', ''),
            'img': img,
            'stream': stream if stream.startswith('http') else '',
        })
    return out


def main():
    pool, by_district = [], {}
    for did, label in DISTRICTS:
        try:
            cams = cameras_from(did)
            cams.sort(key=lambda c: (not c['stream'], c['name']))   # live-capable first
            by_district[did] = (label, len(cams))
            # take a handful from each district rather than letting one dominate
            pool.extend(cams[:15])
            print('  D%s %-14s %4d in-service cameras with an image' % (did, label, len(cams)))
        except Exception as exc:
            print('  D%s failed: %s' % (did, exc))

    if not pool:
        print('no cameras parsed — aborting so as not to clobber cams.js')
        return 2

    # verify BOTH the still image and the live stream: the panel advertises live video,
    # so a camera without a playable stream is no use here.
    verified, seen, checked = [], set(), 0
    for c in pool[:MAX_VERIFY]:
        key = c['name'].lower()
        if key in seen:
            continue
        seen.add(key)
        checked += 1
        if not verify_image(c['img']):
            continue
        ok, res = verify_stream(c['stream'])
        if not ok:
            continue
        c['res'] = res
        verified.append(c)
        if len(verified) >= WANT * 3:
            break
    print('  verified with live video: %d of %d checked' % (len(verified), checked))

    if not verified:
        print('no camera had BOTH a working image and a playable live stream — aborting')
        return 2

    # interleave districts so the grid shows a spread of the state, not twelve cameras
    # from whichever district happened to be fetched first
    buckets, order = {}, []
    for c in verified:
        buckets.setdefault(c['district'], []).append(c)
    order = sorted(buckets, key=lambda d: -len(buckets[d]))
    picked = []
    while len(picked) < WANT and any(buckets.values()):
        for d in order:
            if buckets[d]:
                picked.append(buckets[d].pop(0))
                if len(picked) >= WANT:
                    break

    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'source': 'Caltrans CWWP2',
        'attribution': 'Cameras: California Department of Transportation (Caltrans), public traveller-information data.',
        'note': 'Public highway CCTV. Images refresh every 1-5 minutes; some cameras also carry live video.',
        'districts': {d: {'label': v[0], 'available': v[1]} for d, v in by_district.items()},
        'count': len(picked),
        'cams': picked,
    }
    content = ('// AUTO-GENERATED by fetch_cams.py — do not edit by hand.\n'
               '// Public CCTV snapshots (and live HLS where available) from Caltrans CWWP2:\n'
               '// a source that publishes JSON for integration and charges nothing for it.\n'
               '// Every camera below was verified to return a real image before being written.\n'
               'window.CAMS = ' + json.dumps(data, ensure_ascii=False) + ';\n')
    open(OUT, 'w', encoding='utf-8').write(content)
    live = sum(1 for c in picked if c['stream'])
    used = sorted({c['district'] for c in picked})
    print('wrote cams.js: %d cameras (%d with live video) from %d districts %s'
          % (len(picked), live, len(used), '/'.join(used)))

    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'cams.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'cams: public CCTV snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
