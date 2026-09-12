#!/usr/bin/env python3
"""fetch_outbreaks.py — pull live disease-outbreak reports into outbreaks.js.

Source: WHO Disease Outbreak News (DON) — the World Health Organization's official
outbreak bulletins. Real, keyless JSON API:
    https://www.who.int/api/news/diseaseoutbreaknews

WHO sends no CORS headers, so this runs server-side and writes `outbreaks.js`
(window.OUTBREAKS) that the dashboard reads same-origin. Each item's country is
parsed from its title and geocoded via a built-in country centroid table so the
World map / 3D globe can place an outbreak marker. Run on an interval via cron.

Usage:
    python3 fetch_outbreaks.py            # write outbreaks.js in place (if changed)
    python3 fetch_outbreaks.py --commit   # write + commit + push (only when changed)
"""
import datetime, json, os, re, subprocess, sys, urllib.request, urllib.parse

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'world-monitor', 'outbreaks.js')
REPO = os.path.join(HOME, 'world-monitor')
API = ('https://www.who.int/api/news/diseaseoutbreaknews'
       '?%24orderby=PublicationDateAndTime%20desc&%24top=40')
TOP = 30
UA = {'User-Agent': 'WorldMonitor-OutbreakFetcher/1.0 (public WHO Disease Outbreak News)',
      'Accept': 'application/json'}

# country / territory centroids (enough to place WHO DON items on a map)
CC = {
 'Democratic Republic of the Congo': (-4.0, 21.8), 'Democratic Republic of Congo': (-4.0, 21.8),
 'Uganda': (1.4, 32.3), 'Nigeria': (9.1, 8.7), 'Kenya': (0.2, 37.9), 'Tanzania': (-6.4, 34.9),
 'Ethiopia': (9.1, 40.5), 'Sudan': (15.5, 32.5), 'South Sudan': (7.9, 30.0), 'Somalia': (5.2, 46.2),
 'Ghana': (7.9, -1.0), 'Guinea': (9.9, -9.7), 'Liberia': (6.4, -9.4), 'Sierra Leone': (8.5, -11.8),
 'Mali': (17.6, -4.0), 'Cameroon': (7.4, 12.4), 'Chad': (15.5, 18.7), 'Niger': (17.6, 8.1),
 'Senegal': (14.5, -14.5), 'Côte d\'Ivoire': (7.5, -5.5), 'Ivory Coast': (7.5, -5.5),
 'Benin': (9.3, 2.3), 'Togo': (8.6, 0.8), 'Burkina Faso': (12.2, -1.6), 'Angola': (-11.2, 17.9),
 'Zambia': (-13.1, 27.8), 'Zimbabwe': (-19.0, 29.2), 'Malawi': (-13.3, 34.3),
 'Mozambique': (-18.7, 35.5), 'Madagascar': (-18.8, 46.9), 'Rwanda': (-2.0, 29.9),
 'Burundi': (-3.4, 29.9), 'Central African Republic': (6.6, 20.9), 'Gabon': (-0.8, 11.6),
 'Congo': (-0.2, 15.8), 'Republic of the Congo': (-0.2, 15.8), 'Equatorial Guinea': (1.7, 10.3),
 'Egypt': (26.8, 30.8), 'Libya': (26.3, 17.2), 'Tunisia': (33.9, 9.5), 'Morocco': (31.8, -7.1),
 'Algeria': (28.0, 1.7), 'South Africa': (-30.6, 22.9), 'Namibia': (-22.6, 17.1),
 'Botswana': (-22.3, 24.7), 'Gambia': (13.4, -15.3), 'Mauritania': (21.0, -10.9),
 'India': (20.6, 79.0), 'Pakistan': (30.4, 69.3), 'Bangladesh': (23.7, 90.4), 'Nepal': (28.4, 84.1),
 'Sri Lanka': (7.9, 80.8), 'Afghanistan': (33.9, 67.7), 'China': (35.9, 104.2), 'Japan': (36.2, 138.3),
 'South Korea': (35.9, 127.8), 'Republic of Korea': (35.9, 127.8), 'Indonesia': (-0.8, 113.9),
 'Malaysia': (4.2, 101.98), 'Thailand': (15.9, 100.99), 'Viet Nam': (14.1, 108.3), 'Vietnam': (14.1, 108.3),
 'Philippines': (12.9, 121.8), 'Cambodia': (12.6, 104.9), 'Laos': (19.9, 102.5), 'Myanmar': (21.9, 95.96),
 'Singapore': (1.35, 103.8), 'Saudi Arabia': (23.9, 45.1), 'Yemen': (15.6, 48.5), 'Oman': (21.5, 55.9),
 'Iraq': (33.2, 43.7), 'Iran': (32.4, 53.7), 'Israel': (31.0, 34.9), 'Jordan': (30.6, 36.2),
 'Lebanon': (33.9, 35.9), 'Syria': (34.8, 39.0), 'Turkey': (39.0, 35.2), 'Türkiye': (39.0, 35.2),
 'United States of America': (39.8, -98.6), 'United States': (39.8, -98.6), 'Canada': (56.1, -106.3),
 'Mexico': (23.6, -102.6), 'Brazil': (-14.2, -51.9), 'Argentina': (-38.4, -63.6), 'Chile': (-35.7, -71.5),
 'Peru': (-9.2, -75.0), 'Colombia': (4.6, -74.3), 'Venezuela': (6.4, -66.6), 'Ecuador': (-1.8, -78.2),
 'Bolivia': (-16.3, -63.6), 'Cuba': (21.5, -77.8), 'Haiti': (18.97, -72.3),
 'Dominican Republic': (18.7, -70.2), 'Guatemala': (15.8, -90.2), 'Honduras': (15.2, -86.2),
 'France': (46.2, 2.2), 'Germany': (51.2, 10.5), 'United Kingdom': (55.4, -3.4), 'Spain': (40.5, -3.7),
 'Italy': (41.9, 12.6), 'Netherlands': (52.1, 5.3), 'Belgium': (50.5, 4.5), 'Poland': (51.9, 19.1),
 'Ukraine': (48.4, 31.2), 'Russia': (61.5, 105.3), 'Australia': (-25.3, 133.8), 'New Zealand': (-40.9, 174.9),
 'Fiji': (-17.7, 178.1), 'Papua New Guinea': (-6.3, 143.9), 'Denmark': (56.3, 9.5), 'Sweden': (60.1, 18.6),
 'Norway': (60.5, 8.5), 'Switzerland': (46.8, 8.2), 'Austria': (47.5, 14.6), 'Greece': (39.1, 21.8),
 'Ireland': (53.4, -8.2), 'Portugal': (39.4, -8.2), 'Georgia': (42.3, 43.4), 'Kazakhstan': (48.0, 66.9),
}

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))

def split_title(title):
    """'Ebola ... - Democratic Republic of the Congo' -> (disease, country).

    WHO is inconsistent: most titles use ' - ', but some use a comma
    ('Ebola disease caused by Bundibugyo virus, Democratic Republic of the Congo').
    """
    title = (title or '').strip()
    m = list(re.finditer(r'\s*[-\u2013\u2014]\s+', title))
    if m:
        i = m[-1].start()
        return title[:i].strip(' ,'), title[m[-1].end():].strip(' ,')
    m = list(re.finditer(r',\s+', title))
    if m:
        i = m[-1].start()
        return title[:i].strip(' ,'), title[m[-1].end():].strip(' ,')
    return title, ''

def main():
    try:
        data = fetch(API)
    except Exception as e:
        print('WHO DON fetch failed:', e); sys.exit(1)
    items, ok = [], 0
    for it in (data.get('value') or [])[:TOP]:
        title = (it.get('Title') or '').strip()
        if not title:
            continue
        disease, country = split_title(title)
        coords = CC.get(country)
        url = it.get('ItemDefaultUrl') or ''
        if url.startswith('/'):
            url = 'https://www.who.int' + url
        rec = {
            'id': it.get('DonId') or it.get('Id') or '',
            'title': title,
            'disease': disease,
            'country': country,
            'date': (it.get('PublicationDateAndTime') or '')[:10],
            'url': url,
            'summary': re.sub(r'\s+', ' ', (it.get('Summary') or '')).strip()[:300],
        }
        if coords:
            rec['lat'], rec['lng'] = coords
            ok += 1
        items.append(rec)
    if not items:
        print('parsed 0 outbreak reports — aborting to avoid clobbering'); sys.exit(1)
    # WHO uses these where there is no single country — keep them out of the country list
    NON_COUNTRY = re.compile(r'(?i)^(global|worldwide|world|multi[- ]?countr(y|ies)|multi[- ]?locations?|multiple countries|common)\b')
    countries = sorted({i['country'] for i in items
                        if i['country'] and not NON_COUNTRY.match(i['country'])})
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    out = {
        '_updated': stamp,
        'source': 'WHO Disease Outbreak News',
        'count': len(items),
        'geocoded': ok,
        'countries': countries,
        'latest': items[0]['date'] if items else '',
        'items': items,
    }
    content = ('// AUTO-GENERATED by fetch_outbreaks.py — do not edit by hand.\n'
               '// Live WHO Disease Outbreak News (official outbreak bulletins).\n'
               'window.OUTBREAKS = ' + json.dumps(out, ensure_ascii=False) + ';\n')

    def sig(d):
        return json.dumps([(i['id'], i['date']) for i in d.get('items', [])], sort_keys=True)
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        except Exception:
            prev = {}
    if sig(out) == sig(prev):
        print('outbreaks.js unchanged (%d reports, %s)' % (len(items), stamp))
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote outbreaks.js: %d WHO DON reports, %d geocoded, %d countries, latest %s — %s'
          % (len(items), ok, len(countries), out['latest'], stamp))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'outbreaks.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'outbreak: WHO DON snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0

if __name__ == '__main__':
    sys.exit(main())
