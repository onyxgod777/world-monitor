#!/usr/bin/env python3
"""fetch_daily_events.py — gather the real data behind the World Monitor daily
events image: live RSS headlines (the same feeds app.js uses), the committed
NCMEC amber snapshot, and the committed market snapshot.

Writes daily/events_data.json for the image renderer. No fabrication: every item
comes from a real feed or a committed snapshot.
"""
import json, os, re, html, datetime, urllib.request, xml.etree.ElementTree as ET

HOME = os.path.expanduser('~')
WM = os.path.join(HOME, 'world-monitor')
OUT = os.path.join(WM, 'daily', 'events_data.json')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}

FEEDS = [
    ('World',      'Google News', 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en'),
    ('Markets',    'Google News', 'https://news.google.com/rss/search?q=global%20markets%20economy&hl=en-US&gl=US&ceid=US:en'),
    ('Cyber',      'Google News', 'https://news.google.com/rss/search?q=cybersecurity%20hack%20breach&hl=en-US&gl=US&ceid=US:en'),
    ('Geopolitics','Google News', 'https://news.google.com/rss/search?q=geopolitics%20diplomacy&hl=en-US&gl=US&ceid=US:en'),
    ('Energy',     'Google News', 'https://news.google.com/rss/search?q=oil%20energy%20commodities&hl=en-US&gl=US&ceid=US:en'),
    ('World',      'Al Jazeera',  'https://www.aljazeera.com/xml/rss/all.xml'),
    ('World',      'France 24',   'https://www.france24.com/en/rss'),
    ('Cyber',      '404 Media',   'https://www.404media.co/rss/'),
    ('Climate',    'Grist',       'https://grist.org/feed/'),
]

# representative hubs mirroring app.js's situational map
HUBS = [
    ('United States', 38.9, -77.0, ['us','u.s.','united states','washington','white house','pentagon','america','trump','congress']),
    ('Canada', 45.4, -75.7, ['canada','ottawa']),
    ('Mexico', 19.4, -99.1, ['mexico']),
    ('Brazil', -15.8, -47.9, ['brazil']),
    ('Argentina', -34.6, -58.4, ['argentina','milei']),
    ('United Kingdom', 51.5, -0.1, ['uk ','britain','london','westminster','starmer']),
    ('France', 48.9, 2.35, ['france','paris','macron']),
    ('Germany', 52.5, 13.4, ['germany','berlin','scholz','merz']),
    ('European Union', 50.85, 4.35, ['eu ','european union','brussels']),
    ('Russia', 55.75, 37.6, ['russia','moscow','putin']),
    ('Ukraine', 50.45, 30.5, ['ukraine','kyiv','zelensky']),
    ('Turkey', 41.0, 28.9, ['turkey','erdogan','istanbul']),
    ('Iran', 35.7, 51.4, ['iran','tehran']),
    ('Israel', 32.08, 34.78, ['israel','netanyahu','gaza']),
    ('Saudi Arabia', 24.7, 46.7, ['saudi','riyadh']),
    ('India', 28.6, 77.2, ['india','delhi','modi']),
    ('China', 39.9, 116.4, ['china','beijing','xi jinping','taiwan','chinese']),
    ('Japan', 35.7, 139.7, ['japan','tokyo']),
    ('South Korea', 37.57, 126.98, ['south korea','seoul','korea']),
    ('Taiwan', 25.03, 121.57, ['taiwan']),
    ('Australia', -33.9, 151.2, ['australia','sydney','canberra']),
    ('Egypt', 30.0, 31.2, ['egypt','cairo']),
    ('Nigeria', 6.5, 3.4, ['nigeria','lagos']),
    ('Kenya', -1.3, 36.8, ['kenya','nairobi']),
    ('South Africa', -26.2, 28.0, ['south africa','johannesburg']),
]

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8', 'ignore')

def strip_tags(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()

def clean(s):
    return re.sub(r'\s+', ' ', strip_tags(s)).strip()

def parse_rss(xml_text, region, src):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items
    for it in root.iter('item'):
        t = it.findtext('title')
        if not t:
            continue
        title = clean(t)
        # google news appends " - Source"
        title = re.sub(r'\s+-\s+[^-]+$', '', title) if src == 'Google News' else title
        items.append(dict(title=title, region=region, src=src,
                          pub=clean(it.findtext('pubDate') or ''),
                          link=clean(it.findtext('link') or '')))
    return items

def read_js(path, var):
    try:
        s = open(path, encoding='utf-8').read()
        i = s.index('{')
        j = s.rindex('}')
        return json.loads(s[i:j+1])
    except Exception:
        return None

def main():
    allnews = []
    seen = set()
    for region, src, url in FEEDS:
        try:
            items = parse_rss(fetch(url), region, src)
        except Exception as e:
            print('feed failed', src, url[:50], e); continue
        for it in items:
            k = it['title'].lower()[:80]
            if k in seen or len(it['title']) < 12:
                continue
            seen.add(k); allnews.append(it)
        print('%-14s %-12s %d items' % (region, src, len(items)))

    # regional signal counts (same idea as the live map)
    low = [(n['title'] + ' ' + n['region']).lower() for n in allnews]
    signals = []
    for name, lat, lng, kws in HUBS:
        hits = sum(1 for t in low if any(k in t for k in kws))
        if hits > 0:
            signals.append(dict(name=name, lat=lat, lng=lng, hits=hits))

    amber = read_js(os.path.join(WM, 'amber.js'), 'AMBER') or {}
    fiat = read_js(os.path.join(WM, 'fiatleak.js'), 'FIATLEAK') or {}

    data = dict(
        generated=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        datestr=datetime.datetime.now().strftime('%A, %d %B %Y'),
        total=len(allnews),
        news=allnews[:120],
        signals=sorted(signals, key=lambda s: -s['hits']),
        amber=amber, fiatleak=fiat,
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('TOTAL headlines:', len(allnews), '| signals:', len(signals),
          '| amber cases:', len(amber.get('cases', [])),
          '| wrote', OUT)

if __name__ == '__main__':
    main()
