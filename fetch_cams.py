#!/usr/bin/env python3
"""fetch_cams.py — public CCTV from road and transport authorities worldwide -> cams.js.

Every source here PUBLISHES its cameras for public use — open-data portals, transport
authorities, or an explicitly reusable traveller-information feed. None of them is a
directory of devices discovered because they were left exposed; nothing is scraped from
a camera that its operator did not put out for people to look at.

Sources (all keyless — no account, no API key, no paid tier):
  USA · California   Caltrans CWWP2 ........... still images + real live HLS video
  Singapore          LTA via data.gov.sg ...... still images, ~2 min
  Finland            Fintraffic / Digitraffic . still images, weather-camera network
  Hong Kong          Transport Dept via data.gov.hk . still images, ~2 min

Each camera is VERIFIED with a real request before being written: the image must come
back as actual image bytes (and for video cameras the HLS playlist must resolve to real
segments). A camera that fails is dropped — the panel must never advertise a dead feed.

Usage:
    python3 fetch_cams.py            # write cams.js
    python3 fetch_cams.py --commit   # write, then git commit + push if changed
"""
import datetime
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET

REPO = os.environ.get('WM_REPO_DIR', os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, 'cams.js')
UA = {'User-Agent': 'WorldMonitor-Cams/1.0 (https://worldmonitor.thealpha-secret.xyz; '
                    'contact sunntzu@realvalueofpi.xyz)'}

PER_SOURCE = 6      # cameras to publish from each source
CANDIDATES = 26     # candidates to test per source before giving up
CALTRANS_CANDIDATES = 12   # per district: a deep enough pool to find working live streams
CALTRANS_DISTRICTS = [('3', 'Sacramento'), ('4', 'Bay Area'), ('7', 'Los Angeles'),
                      ('8', 'Inland Empire'), ('11', 'San Diego')]


def get(url, timeout=45, accept='*/*', enc=None):
    h = dict(UA, Accept=accept)
    if enc:
        h['Accept-Encoding'] = enc
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get('Content-Encoding') == 'gzip' or raw[:2] == b'\x1f\x8b':
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        return raw


def getj(url, **kw):
    return json.loads(get(url, accept='application/json', **kw).decode('utf-8', 'replace'))


def verify_image(url):
    """True only if the URL really returns image bytes right now.

    The magic bytes are the actual evidence. Some authorities serve real JPEGs with a
    generic Content-Type (application/octet-stream), so a missing or generic type is
    accepted when the bytes are unambiguously an image — but bytes that are NOT an
    image are rejected no matter what the header claims.
    """
    try:
        req = urllib.request.Request(url, headers=dict(UA, Range='bytes=0-2047'))
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read(16)
            ctype = (r.headers.get('Content-Type') or '').lower()
        if not head:
            return False
        is_image = head[:2] == b'\xff\xd8' or head[:8] == b'\x89PNG\r\n\x1a\n'
        generic = (not ctype) or 'octet-stream' in ctype or 'binary' in ctype
        return is_image and ('image' in ctype or generic)
    except Exception:
        return False


def verify_stream(url):
    """True only if the URL serves a playable HLS playlist with real segments."""
    if not url:
        return False, ''
    try:
        body = get(url, timeout=30).decode('utf-8', 'replace')
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
        vurl = variant if variant.startswith('http') else url.rsplit('/', 1)[0] + '/' + variant
        vbody = get(vurl, timeout=30).decode('utf-8', 'replace')
        if '#EXTINF' not in vbody and '#EXT-X-BYTERANGE' not in vbody:
            return False, ''
        m = re.search(r'RESOLUTION=(\d+x\d+)', body)
        return True, (m.group(1) if m else '')
    except Exception:
        return False, ''


# ───────────────────────── sources ─────────────────────────

def src_caltrans():
    """Caltrans CWWP2 — free of charge and published for integration. Stills + live HLS."""
    out = []
    for did, label in CALTRANS_DISTRICTS:
        try:
            doc = getj('https://cwwp2.dot.ca.gov/data/d%s/cctv/cctvStatusD0%s.json' % (did, did))
        except Exception as exc:
            print('    D%s failed: %s' % (did, exc))
            continue
        node = doc.get('data', [])
        items = node if isinstance(node, list) else [node]
        cams = []
        for it in items:
            if not isinstance(it, dict):
                continue
            inner = it.get('cctv')
            if isinstance(inner, dict):
                cams.append(inner)
            elif isinstance(inner, list):
                cams.extend(x for x in inner if isinstance(x, dict))
            else:
                cams.append(it)
        good = []
        for c in cams:
            loc = c.get('location') or {}
            img = ((c.get('imageData') or {}).get('static') or {}).get('currentImageURL') or ''
            stream = (c.get('imageData') or {}).get('streamingVideoURL') or ''
            name = (loc.get('locationName') or '').strip()
            if str(c.get('inService', '')).lower() != 'true' or not name or not img.startswith('http'):
                continue
            good.append({'name': name, 'route': loc.get('route', ''), 'place': loc.get('nearbyPlace', ''),
                         'county': loc.get('county', ''), 'region': 'USA · California',
                         'img': img, 'stream': stream if stream.startswith('http') else '',
                         'kind': 'video' if stream.startswith('http') else 'image',
                         'source': 'Caltrans', 'district': did})
        good.sort(key=lambda c: (c['kind'] != 'video', c['name']))
        # interleave districts so California is not one city; keep a deep enough
        # candidate pool that several working live streams are actually tested
        for c in good[:CALTRANS_CANDIDATES]:
            out.append(c)
    return out


def src_singapore():
    """LTA traffic images via data.gov.sg — Singapore's open data portal."""
    out = []
    try:
        d = getj('https://api.data.gov.sg/v1/transport/traffic-images')
    except Exception as exc:
        print('    data.gov.sg failed: %s' % exc)
        return out
    for cam in (d.get('items') or [{}])[0].get('cameras', []):
        img = cam.get('image', '')
        if not img.startswith('http'):
            continue
        loc = cam.get('location') or {}
        out.append({'name': 'LTA camera %s' % cam.get('camera_id', ''),
                    'route': '', 'place': '', 'county': '',
                    'region': 'Singapore',
                    'img': img, 'stream': '', 'kind': 'image',
                    'source': 'LTA · data.gov.sg',
                    'lat': loc.get('latitude'), 'lon': loc.get('longitude')})
    return out


def src_finland():
    """Fintraffic weather cameras via Digitraffic — Finnish open traffic data."""
    out = []
    try:
        d = getj('https://tie.digitraffic.fi/api/weathercam/v1/stations', enc='gzip')
    except Exception as exc:
        print('    digitraffic failed: %s' % exc)
        return out
    for f in d.get('features', []):
        props = f.get('properties') or {}
        presets = props.get('presets') or []
        if not presets:
            continue
        pid = presets[0].get('id')
        if not pid:
            continue
        coords = (f.get('geometry') or {}).get('coordinates') or [None, None]
        name = props.get('name') or props.get('id') or pid
        out.append({'name': str(name).replace('_', ' '),
                    'route': '', 'place': props.get('municipality', '') or '', 'county': '',
                    'region': 'Finland',
                    'img': 'https://weathercam.digitraffic.fi/%s.jpg' % pid,
                    'stream': '', 'kind': 'image',
                    'source': 'Fintraffic · Digitraffic',
                    'lat': coords[1], 'lon': coords[0]})
    return out


def src_hongkong():
    """Hong Kong Transport Department traffic snapshot images via data.gov.hk."""
    out = []
    try:
        raw = get('https://static.data.gov.hk/td/traffic-snapshot-images/code/'
                  'Traffic_Camera_Locations_En.xml', accept='application/xml')
        root = ET.fromstring(raw)
    except Exception as exc:
        print('    data.gov.hk failed: %s' % exc)
        return out
    for im in root.iter():
        if im.tag.split('}')[-1].lower() != 'image':
            continue
        kv = {ch.tag.split('}')[-1].lower(): (ch.text or '').strip() for ch in im}
        key = kv.get('key', '')
        if not key:
            continue
        desc = kv.get('description') or key
        place = ' · '.join(x for x in (kv.get('region'), kv.get('district')) if x)
        out.append({'name': desc, 'route': '', 'place': place, 'county': '',
                    'region': 'Hong Kong',
                    'img': 'https://tdcctv.data.one.gov.hk/%s.JPG' % key,
                    'stream': '', 'kind': 'image',
                    'source': 'HK Transport Dept · data.gov.hk'})
    return out


SOURCES = [
    ('USA · California', src_caltrans),
    ('Singapore', src_singapore),
    ('Finland', src_finland),
    ('Hong Kong', src_hongkong),
]


def main():
    picked, summary = [], {}
    for label, fn in SOURCES:
        try:
            cands = fn()
        except Exception as exc:
            print('  %-18s source error: %s' % (label, exc))
            summary[label] = (0, 0)
            continue
        # a camera appears once even if the feed repeats it
        seen, uniq = set(), []
        for c in cands:
            k = (c['name'].lower(), c['img'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(c)
        # prefer live-video cameras, then take a spread
        uniq.sort(key=lambda c: (c['kind'] != 'video',))
        # Prefer live video: exhaust the video candidates first, and only fall back to
        # stills to fill whatever slots are left. A camera whose stream fails is kept as
        # a still (honestly relabelled) but must NOT take a slot from a working stream.
        vids, stills = [], []
        for c in uniq[:CANDIDATES]:
            if len(vids) >= PER_SOURCE:
                break
            if not verify_image(c['img']):
                continue
            if c['kind'] == 'video':
                ok, res = verify_stream(c['stream'])
                if ok:
                    c['res'] = res
                    vids.append(c)
                    continue
                c['kind'], c['stream'] = 'image', ''      # honest: keep the still, drop the claim
            if len(stills) < PER_SOURCE:
                stills.append(c)
        good = vids + stills[:max(0, PER_SOURCE - len(vids))]
        picked.extend(good)
        summary[label] = (len(uniq), len(good), sum(1 for g in good if g['kind'] == 'video'))
        print('  %-18s %5d available -> %d published (%d with live video)'
              % (label, len(uniq), len(good), summary[label][2]))

    if not picked:
        print('nothing verified from any source — aborting so as not to clobber cams.js')
        return 2

    videos = sum(1 for c in picked if c['kind'] == 'video')
    regions = sorted({c['region'] for c in picked})
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'source': 'Caltrans · LTA Singapore · Fintraffic Finland · HK Transport Dept',
        'attribution': 'Public cameras published by their operators: Caltrans CWWP2 (USA), '
                       'LTA via data.gov.sg (Singapore), Fintraffic via Digitraffic (Finland), '
                       'Transport Department via data.gov.hk (Hong Kong).',
        'note': 'Public road and transport cameras. Still images refresh every 1-5 minutes; '
                'cameras marked live carry real HLS video.',
        'regions': regions,
        'count': len(picked),
        'live': videos,
        'cams': picked,
    }
    content = ('// AUTO-GENERATED by fetch_cams.py — do not edit by hand.\n'
               '// Public cameras published by road and transport authorities for reuse.\n'
               '// Every camera here was verified to return a real image (and, for video\n'
               '// cameras, a playable HLS playlist) before being written.\n'
               'window.CAMS = ' + json.dumps(data, ensure_ascii=False) + ';\n')
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote cams.js: %d cameras from %d regions (%d with live video)'
          % (len(picked), len(regions), videos))

    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'cams.js'], check=True)
        try:
            subprocess.run(['git', '-C', REPO, 'commit', '-m',
                            'cams: world public CCTV snapshot (%s)' % stamp[:16]], check=True)
            subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
            print('committed + pushed')
        except subprocess.CalledProcessError as exc:
            print('git step failed (%s) — caller can retry the push' % exc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
