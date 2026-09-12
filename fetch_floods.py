#!/usr/bin/env python3
"""fetch_floods.py — pull CURRENT flood alerts into floods.js.

Two real, keyless sources:

  * GDACS current-disasters feed — worldwide, and filtered to events GDACS
    itself marks `iscurrent=true`, so the report never shows a past event.
        https://www.gdacs.org/xml/rss.xml
    (The /gdacsapi/.../SEARCH endpoint returns the whole historical catalogue,
    which is why it is NOT used here — it produced expired alerts.)
  * NOAA / NWS active flood warnings (US backfill, real-time):
        https://api.weather.gov/alerts/active?event=Flood Warning

GDACS sends no CORS headers, so this runs server-side and writes `floods.js`
(window.FLOODS) that the dashboard reads same-origin. Run on an interval via cron.

Usage:
    python3 fetch_floods.py            # write floods.js in place (if changed)
    python3 fetch_floods.py --commit   # write + commit + push (only when changed)
"""
import datetime, email.utils, json, os, re, subprocess, sys, urllib.request

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'world-monitor', 'floods.js')
REPO = os.path.join(HOME, 'world-monitor')
GDACS_RSS = 'https://www.gdacs.org/xml/rss.xml'
NWS = 'https://api.weather.gov/alerts/active?event=Flood%20Warning'
UA = {'User-Agent': 'WorldMonitor-FloodFetcher/1.0 (public GDACS + NOAA NWS open data)',
      'Accept': 'application/xml, application/json, text/xml, */*'}


def fetch(url, accept=None):
    hdr = dict(UA)
    if accept:
        hdr['Accept'] = accept
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'ignore')


def iso_date(rfc):
    """'Thu, 10 Sep 2026 01:00:00 GMT' -> '2026-09-10'."""
    try:
        return email.utils.parsedate_to_datetime(rfc).date().isoformat()
    except Exception:
        return ''


def tag(block, name):
    m = re.search(r'<%s>(.*?)</%s>' % (name, name), block, re.S)
    return m.group(1).strip() if m else ''


def parse_gdacs(xml):
    today = datetime.date.today().isoformat()
    out = []
    for m in re.finditer(r'<item>(.*?)</item>', xml, re.S):
        it = m.group(1)
        if tag(it, 'gdacs:eventtype') != 'FL':
            continue
        # freshness guard: GDACS' own current flag, and the event must not have ended
        if tag(it, 'gdacs:iscurrent').lower() != 'true':
            continue
        to_date = iso_date(tag(it, 'gdacs:todate'))
        if to_date and to_date < today:
            continue
        gm = re.search(r'<geo:lat>([-\d.]+)</geo:lat>\s*<geo:long>([-\d.]+)</geo:long>', it)
        if not gm:
            continue
        title = tag(it, 'title')
        level = tag(it, 'gdacs:alertlevel') or 'Green'
        # 'Green flood alert in Slovenia' -> country
        cm = re.search(r'\bin\s+(.+)$', title)
        out.append({
            'id': tag(it, 'guid') or tag(it, 'gdacs:eventid'),
            'name': title,
            'level': level,
            'country': (cm.group(1).strip() if cm else ''),
            'lat': round(float(gm.group(1)), 4),
            'lng': round(float(gm.group(2)), 4),
            'from': iso_date(tag(it, 'gdacs:fromdate')),
            'to': to_date,
            'status': 'ongoing' if (not to_date or to_date >= today) else 'recent',
            'modified': iso_date(tag(it, 'gdacs:datemodified')),
            'report': (tag(it, 'link') or '').replace('&amp;', '&'),
            'detail': re.sub(r'\s+', ' ', tag(it, 'description'))[:220],
            'src': 'GDACS',
        })
    return out


def parse_nws(txt):
    out = []
    try:
        d = json.loads(txt)
    except Exception:
        return out
    for f in (d.get('features') or [])[:80]:
        try:
            p = f.get('properties') or {}
            area = (p.get('areaDesc') or '').strip()
            out.append({
                'id': (f.get('id') or '')[:64],
                'name': (p.get('event') or 'Flood Warning').strip() + ((' — ' + area) if area else ''),
                'level': 'Red' if (p.get('severity') or '').lower() in ('severe', 'extreme') else 'Orange',
                'severity': p.get('severity') or '',
                'sent': (p.get('sent') or '')[:16],
                'status': 'ongoing',
                'src': 'NWS',
            })
        except Exception:
            continue
    return out


def main():
    gdacs, nws, ok = [], [], 0
    try:
        gdacs = parse_gdacs(fetch(GDACS_RSS, 'application/xml, text/xml'))
        ok += 1
    except Exception as e:
        print('GDACS fetch failed:', e)
    try:
        nws = parse_nws(fetch(NWS, 'application/json, application/geo+json'))
        ok += 1
    except Exception as e:
        print('NWS fetch failed:', e)
    if not gdacs and not nws:
        print('parsed 0 current flood alerts from both sources — aborting to avoid clobbering')
        sys.exit(1)

    by_level = {lvl: sum(1 for e in gdacs if e['level'] == lvl) for lvl in ('Red', 'Orange', 'Green')}
    countries = sorted({e['country'] for e in gdacs if e['country']})
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'source': 'GDACS + NOAA/NWS',
        'sources': '%d/2 feeds' % ok,
        'currentOnly': True,
        'count': len(gdacs) + len(nws),
        'global': len(gdacs),
        'usWarnings': len(nws),
        'red': by_level['Red'],
        'orange': by_level['Orange'],
        'green': by_level['Green'],
        'countries': countries,
        'events': gdacs,
        'usEvents': nws[:40],
    }
    content = ('// AUTO-GENERATED by fetch_floods.py — do not edit by hand.\n'
               '// CURRENT flood alerts only: GDACS current-disasters feed (iscurrent) + NOAA/NWS.\n'
               'window.FLOODS = ' + json.dumps(data, ensure_ascii=False) + ';\n')

    def sig(d):
        return json.dumps([(e['id'], e['level']) for e in d.get('events', [])] +
                          [(e['id'], e['level']) for e in d.get('usEvents', [])], sort_keys=True)
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        except Exception:
            prev = {}
    if sig(data) == sig(prev):
        print('floods.js unchanged (%d current global, %d US, %s)' % (len(gdacs), len(nws), stamp))
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote floods.js: %d CURRENT global (Red %d / Orange %d / Green %d) + %d US warnings, %d countries, %s'
          % (len(gdacs), by_level['Red'], by_level['Orange'], by_level['Green'], len(nws), len(countries), stamp))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'floods.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'flood: GDACS/NWS CURRENT flood snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
