#!/usr/bin/env python3
"""build_gazetteer.py — build gazetteer.js: the place table the World map and 3D
globe use to put a live headline somewhere on the Earth.

Why this exists
---------------
The dashboard used to place news with 26 hand-written "hub" keyword lists, so any
headline that named a country, city or region outside those lists simply vanished
from the map (measured: ~72% of the live feed matched nothing). This builds a real
place table instead:

  * every ISO 3166 country from the mledoze/countries dataset (public, no key):
    common + official name, capital, English demonym and ASCII alt-spellings,
    each pinned to the dataset's own country centroid;
  * curated aliases for names the dataset does not carry (cities, states,
    provinces, national adjectives) — each alias folds into its country entry, so
    a headline saying "Leipzig" lands on Germany's centroid, not on Leipzig;
  * multi-country regions and waterways (Black Sea, Sahel, Strait of Hormuz …)
    whose coordinates are resolved from OpenStreetMap Nominatim at build time and
    stored here, so the published page needs no lookup.

Honesty: placement is keyword-derived and country-level. A headline is pinned to
the place it names, never to where the story's facts were sourced. app.js labels
it that way in the marker popup, and unplaceable headlines stay off the map.

Usage:
    python3 build_gazetteer.py                 # write gazetteer.js (network)
    python3 build_gazetteer.py --source-file /tmp/mledoze.json
    python3 build_gazetteer.py --regions-only  # re-resolve only the region list
"""
import argparse, datetime, json, os, re, sys, time, urllib.parse, urllib.request

HOME = os.path.expanduser('~')
REPO = os.environ.get('WM_REPO_DIR') or os.path.join(HOME, 'world-monitor')
OUT = os.path.join(REPO, 'gazetteer.js')
COUNTRIES_URL = 'https://raw.githubusercontent.com/mledoze/countries/master/countries.json'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'
UA = {'User-Agent': 'WorldMonitor-GazetteerBuilder/1.0 (public OSM Nominatim, contact: admin@thealpha-secret.xyz)',
      'Accept-Language': 'en-US,en;q=0.9'}

# Spelling variants / abbreviations the dataset does not list per country.
COUNTRY_ALIASES = {
    'United States': ['u.s.', 'u.s', 'usa', 'washington d.c.', 'washington dc', 'white house',
                      'pentagon', 'capitol hill', 'america', 'wall street', 'silicon valley',
                      '=US', '=U.S.', '=USA', 'state department', 'new york', 'new york city',
                      'nyc', 'california', 'los angeles', 'chicago', 'texas', 'florida',
                      'michigan', 'ohio', 'arizona', 'pennsylvania', 'manhattan',
                      'washington state', 'puerto rico', 'hawaii', 'alaska'],
    'United Kingdom': ['u.k.', 'u.k', 'uk', '=UK', 'britain', 'london', 'westminster', 'england',
                       'scotland', 'wales', 'northern ireland', 'downing street'],
    'United Arab Emirates': ['u.a.e.', 'u.a.e', '=UAE', 'abu dhabi'],
    'Belgium': ['brussels', '=EU', 'european union', 'european commission', 'nato'],
    'Netherlands': ['holland', 'the hague', 'amsterdam', 'rotterdam'],
    'Czechia': ['czech republic', 'prague'],
    'North Macedonia': ['macedonia', 'skopje'],
    'Democratic Republic of the Congo': ['dr congo', 'drc', 'dr congo', 'kinshasa', 'congolese'],
    'Republic of the Congo': ['congo-brazzaville', 'brazzaville'],
    'Ivory Coast': ["cote d'ivoire", 'côte d’ivoire', 'abidjan'],
    'Cape Verde': ['cabo verde'],
    'Burma': ['myanmar', 'rangoon', 'naypyidaw'],
    'Eswatini': ['swaziland'],
    'Turkey': ['türkiye', 'turkiye'],
    'Russia': ['kremlin', 'siberia', 'irkutsk', 'chechnya', 'dagestan', 'tomsk', 'moscow'],
    'Ukraine': ['kyiv', 'kiev', 'donbas', 'donetsk', 'luhansk', 'crimea', 'odesa', 'kharkiv'],
    'Germany': ['berlin', 'bavaria', 'saxony', 'leipzig', 'munich', 'frankfurt', 'hamburg'],
    'France': ['paris', 'normandy', 'marseille', 'lyon', 'toulouse'],
    'Italy': ['rome', 'milan', 'tuscany', 'lombardy', 'venice', 'naples', 'sicily'],
    'Spain': ['madrid', 'catalonia', 'barcelona', 'basque', 'andalusia', 'galicia', 'málaga'],
    'Greece': ['athens', 'crete'],
    'Poland': ['warsaw', 'silesia', 'krakow'],
    'Sweden': ['stockholm'], 'Norway': ['oslo'], 'Denmark': ['copenhagen'],
    'Finland': ['helsinki'], 'Ireland': ['dublin', 'belfast'],
    'Switzerland': ['geneva', 'zurich', 'davos'],
    'South Africa': ['johannesburg', 'cape town', 'pretoria', 'durban'],
    'Nigeria': ['lagos', 'abuja', 'ebonyi', 'ogun', 'rivers state', 'borno', 'kano'],
    'Kenya': ['nairobi', 'mombasa'],
    'Ethiopia': ['addis ababa', 'tigray'],
    'Egypt': ['cairo', 'sinai', 'alexandria'],
    'Sudan': ['khartoum', 'darfur'],
    'Somalia': ['mogadishu', 'somaliland'],
    'Mali': ['bamako'], 'Burkina Faso': ['ouagadougou'],
    'Niger': ['niamey'], 'Chad': ['ndjamena', "n'djamena"],
    'Morocco': ['rabat', 'casablanca', 'western sahara'],
    'Algeria': ['algiers'], 'Libya': ['tripoli', 'benghazi'],
    'Tunisia': ['tunis'], 'Ghana': ['accra'], 'Senegal': ['dakar'],
    'Uganda': ['kampala'], 'Tanzania': ['dar es salaam', 'zanzibar', 'dodoma'],
    'Zimbabwe': ['harare'], 'Zambia': ['lusaka'], 'Mozambique': ['maputo', 'cabo delgado'],
    'Namibia': ['windhoek'], 'Botswana': ['gaborone'], 'Angola': ['luanda'],
    'Cameroon': ['yaounde'], 'Rwanda': ['kigali'], 'Malawi': ['lilongwe'],
    'India': ['delhi', 'new delhi', 'mumbai', 'kashmir', 'kolkata', 'chennai', 'bengaluru'],
    'Pakistan': ['islamabad', 'karachi', 'lahore', 'peshawar', 'balochistan', 'sindh'],
    'Afghanistan': ['kabul', 'kandahar', 'taliban'],
    'Bangladesh': ['dhaka'], 'Sri Lanka': ['colombo'],
    'Nepal': ['kathmandu'], 'Haiti': ['port-au-prince'],
    'China': ['beijing', 'shanghai', 'hong kong', 'macau', 'guangzhou', 'shenzhen', 'xinjiang',
              'tibet', 'uyghur', 'chinese'],
    'Taiwan': ['taipei', 'taiwanese'],
    'Japan': ['tokyo', 'osaka', 'okinawa'],
    'South Korea': ['seoul', 'korean peninsula'],
    'North Korea': ['pyongyang', 'dprk'],
    'Indonesia': ['jakarta', 'bali', 'java', 'sumatra', 'sulawesi'],
    'Philippines': ['manila', 'mindanao', 'philippine', 'filipino'],
    'Thailand': ['bangkok', 'phuket'],
    'Vietnam': ['hanoi', 'saigon', 'ho chi minh'],
    'Malaysia': ['kuala lumpur'], 'Singapore': ['singaporean'],
    'Australia': ['sydney', 'melbourne', 'canberra', 'queensland', 'western australia'],
    'New Zealand': ['auckland', 'wellington'],
    'Canada': ['ottawa', 'toronto', 'vancouver', 'montreal', 'alberta', 'quebec', 'ontario'],
    'Mexico': ['mexico city', 'juarez', 'sinaloa', 'tijuana'],
    'Brazil': ['brasilia', 'sao paulo', 'rio de janeiro', 'amazon', 'amazonia'],
    'Argentina': ['buenos aires', 'milei'],
    'Chile': ['santiago'], 'Peru': ['lima'], 'Colombia': ['bogota', 'medellin'],
    'Venezuela': ['caracas', 'maduro'], 'Ecuador': ['quito'], 'Bolivia': ['la paz'],
    'Cuba': ['havana'], 'Jamaica': ['kingston'], 'Panama': ['panama city'],
    'Guatemala': ['guatemala city'], 'Honduras': ['tegucigalpa'],
    'Israel': ['jerusalem', 'tel aviv', 'idf'],
    'Palestine': ['west bank', 'gaza strip', 'ramallah', 'rafah'],
    'Iran': ['tehran', 'persian', 'irgc'],
    'Iraq': ['baghdad', 'mosul', 'erbil', 'kurdistan'],
    'Syria': ['damascus', 'aleppo', 'idlib'],
    'Lebanon': ['beirut', 'hezbollah'],
    'Yemen': ['sanaa', 'aden', 'houthi', 'houthis', 'ansarallah'],
    'Saudi Arabia': ['riyadh', 'jeddah', 'mbs', 'aramco'],
    'Jordan': ['amman'], 'Qatar': ['doha'], 'Kuwait': ['kuwait city'],
    'Oman': ['muscat'], 'Bahrain': ['manama'],
    'Georgia': ['tbilisi', 'south ossetia', 'abkhazia'],
    'Armenia': ['yerevan', 'nagorno-karabakh'],
    'Azerbaijan': ['baku', 'nagorno-karabakh'],
    'Kazakhstan': ['astana', 'almaty'], 'Uzbekistan': ['tashkent'],
    'Moldova': ['chisinau', 'transnistria'],
    'Belarus': ['minsk', 'lukashenko'],
    'Serbia': ['belgrade', 'kosovo'], 'Kosovo': ['pristina'],
    'Bosnia and Herzegovina': ['sarajevo'],
    'Croatia': ['zagreb'], 'Slovakia': ['bratislava'], 'Hungary': ['budapest'],
    'Romania': ['bucharest'], 'Bulgaria': ['sofia'], 'Albania': ['tirana'],
}

# Multi-country spaces: coordinates are resolved at build time from Wikipedia's
# coordinate property (with OpenStreetMap Nominatim as the fallback for names
# Wikipedia has no coordinates for), so nothing here is typed from memory.
# (keyword as it appears in a headline, Wikipedia article title, map label)
REGIONS = [
    ('black sea', 'Black Sea', 'Black Sea'),
    ('red sea', 'Red Sea', 'Red Sea'),
    ('bab el-mandeb', 'Bab-el-Mandeb', 'Bab el-Mandeb strait'),
    ('strait of hormuz', 'Strait of Hormuz', 'Strait of Hormuz'),
    ('persian gulf', 'Persian Gulf', 'Persian Gulf'),
    ('gulf of aden', 'Gulf of Aden', 'Gulf of Aden'),
    ('south china sea', 'South China Sea', 'South China Sea'),
    ('taiwan strait', 'Taiwan Strait', 'Taiwan Strait'),
    ('east china sea', 'East China Sea', 'East China Sea'),
    ('mediterranean', 'Mediterranean Sea', 'Mediterranean Sea'),
    ('suez canal', 'Suez Canal', 'Suez Canal'),
    ('panama canal', 'Panama Canal', 'Panama Canal'),
    ('sahel', 'Sahel', 'Sahel'),
    ('horn of africa', 'Horn of Africa', 'Horn of Africa'),
    ('balkans', 'Balkans', 'Balkans'),
    ('caucasus', 'Caucasus', 'Caucasus'),
    ('karachay-cherkessia', 'Karachay-Cherkessia', 'Karachay-Cherkessia'),
    ('middle east', 'Middle East', 'Middle East'),
    ('west africa', 'West Africa', 'West Africa'),
    ('east africa', 'East Africa', 'East Africa'),
    ('southern africa', 'Southern Africa', 'Southern Africa'),
    ('central asia', 'Central Asia', 'Central Asia'),
    ('southeast asia', 'Southeast Asia', 'Southeast Asia'),
    ('latin america', 'Latin America', 'Latin America'),
    ('caribbean', 'Caribbean', 'Caribbean'),
    ('pacific islands', 'Oceania', 'Pacific islands'),
    ('arctic', 'Arctic', 'Arctic'),
    ('antarctica', 'Antarctica', 'Antarctica'),
    ('sahara', 'Sahara', 'Sahara'),
    ('amazon rainforest', 'Amazon rainforest', 'Amazon basin'),
    ('darfur', 'Darfur', 'Darfur'),
    ('tigray', 'Tigray Region', 'Tigray'),
    ('kurdistan', 'Kurdistan', 'Kurdistan'),
    ('kashmir', 'Kashmir', 'Kashmir'),
    ('donbas', 'Donbas', 'Donbas'),
    ('crimea', 'Crimea', 'Crimea'),
    ('sinai', 'Sinai Peninsula', 'Sinai'),
    ('west bank', 'West Bank', 'West Bank'),
    ('gaza strip', 'Gaza Strip', 'Gaza Strip'),
    ('balochistan', 'Balochistan', 'Balochistan'),
    ('somaliland', 'Somaliland', 'Somaliland'),
    ('western sahara', 'Western Sahara', 'Western Sahara'),
    ('korean peninsula', 'Korean Peninsula', 'Korean peninsula'),
    ('levant', 'Levant', 'Levant'),
    ('maghreb', 'Maghreb', 'Maghreb'),
]

# Short tokens that match too much English prose to be safe as place keywords.
STOP = {'us', 'the', 'and', 'of', 'in', 'a', 'an', 'un', 'eu', 'as', 'is', 'it', 'no', 'so',
        'guinea' }


def fetch_countries(source_file=None):
    if source_file:
        return json.load(open(source_file, encoding='utf-8'))
    req = urllib.request.Request(COUNTRIES_URL, headers={'User-Agent': UA['User-Agent']})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def country_keywords(c):
    out = set()
    for v in [c['name'].get('common'), c['name'].get('official')]:
        if v:
            out.add(v.lower())
    for cap in (c.get('capital') or []):
        out.add(cap.lower())
    dem = (c.get('demonyms') or {}).get('eng') or {}
    for v in (dem.get('m'), dem.get('f')):
        if v:
            out.add(v.lower())
    for a in (c.get('altSpellings') or []):
        a = a.strip().lower()
        if len(a) < 3 or a in STOP:
            continue
        if not re.fullmatch(r"[a-z][a-z .'\-]*", a):
            continue
        out.add(a)
        if '-' in a:
            out.add(a.replace('-', ' '))
    # '=TOKEN' aliases stay uppercase: they are matched case-sensitively so short
    # forms (US, UK, EU) cannot fire on ordinary prose.
    out |= {a if a.startswith('=') else a.lower()
            for a in COUNTRY_ALIASES.get(c['name']['common'], [])}
    # '=TOKEN' means: match this one case-sensitively (short forms like US/UK that
    # would otherwise hit ordinary prose). The marker makes short tokens safe.
    keep = []
    for k in out:
        if k.startswith('='):
            if len(k) >= 3:                       # '=US', '=UK', '=EU'
                keep.append(k)
        elif len(k) >= 3 and k not in STOP:
            keep.append(k)
    return sorted(keep)


def geocode(name, attempts=4):
    """One Nominatim lookup, backing off on rate limits (they are common on the
    shared public endpoint). Returns (lat, lng, display) or None."""
    url = NOMINATIM + '?' + urllib.parse.urlencode(
        {'q': name, 'format': 'jsonv2', 'limit': 1, 'addressdetails': 0})
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                hits = json.loads(r.read().decode('utf-8', 'ignore'))
            if not hits:
                return None
            h = hits[0]
            return round(float(h['lat']), 3), round(float(h['lon']), 3), h.get('display_name', '')[:80]
        except Exception as e:
            if i == attempts - 1:
                raise
            wait = 15 * (i + 1)
            print('    %s -> %s; retrying in %ds' % (name, e, wait))
            time.sleep(wait)
    return None


def wikipedia_coords(titles, batch=40):
    """Batched geodata: {article title: (lat, lng, display)} from the Wikipedia
    coordinate property (action=query&prop=coordinates)."""
    out = {}
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        url = 'https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(
            {'action': 'query', 'prop': 'coordinates', 'titles': '|'.join(chunk),
             'format': 'json', 'redirects': 1})
        req = urllib.request.Request(url, headers={'User-Agent': UA['User-Agent']})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode('utf-8', 'ignore'))
        except Exception as e:
            print('  wikipedia lookup failed: %s' % e)
            continue
        q = data.get('query') or {}
        alias = {}
        for k in ('normalized', 'redirects'):
            for m in q.get(k) or []:
                alias[m.get('from')] = m.get('to')
        for page in (q.get('pages') or {}).values():
            co = page.get('coordinates') or []
            if not co:
                continue
            name = page.get('title')
            hit = (round(float(co[0]['lat']), 3), round(float(co[0]['lon']), 3), name)
            out[name] = hit
            for src, dst in alias.items():
                if dst == name:
                    out[src] = hit
    return out


# Wikidata descriptions that mean "this is not the geographic region we want".
BAD_DESC = ('war', 'battle', 'conflict', 'invasion', 'offensive', 'film', 'album', 'song',
            'novel', 'book', 'company', 'university', 'street', 'neighborhood',
            'neighbourhood', 'township', 'county', 'village', 'city in', 'genus', 'species',
            'family name', 'given name', 'tv series', 'video game', 'football', 'basketball',
            'album', 'band', 'magazine', 'newspaper', 'suburb', 'district of')


def wikidata_coords(name):
    """Coordinates for a geographic region from Wikidata's P625, with the entity
    description used to reject look-alikes (war articles, films, townships …).
    Returns (lat, lng, label, qid) or None."""
    def api(base, params):
        req = urllib.request.Request(base + '?' + urllib.parse.urlencode(params),
                                     headers={'User-Agent': UA['User-Agent']})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8', 'ignore'))
    try:
        search = api('https://www.wikidata.org/w/api.php',
                     {'action': 'wbsearchentities', 'search': name, 'language': 'en',
                      'format': 'json', 'limit': 5, 'type': 'item'})
    except Exception as e:
        print('  wikidata search failed for %s: %s' % (name, e))
        return None
    for hit in search.get('search') or []:
        desc = (hit.get('description') or '').lower()
        if any(b in desc for b in BAD_DESC):
            continue
        if 'disambiguation' in desc:
            continue
        try:
            ent = api('https://www.wikidata.org/w/api.php',
                      {'action': 'wbgetentities', 'ids': hit['id'], 'props': 'claims|labels',
                       'languages': 'en', 'format': 'json'})['entities'][hit['id']]
            claims = (ent.get('claims') or {}).get('P625') or []
            if not claims:
                continue
            v = claims[0]['mainsnak'].get('datavalue', {}).get('value', {})
            return (round(float(v['latitude']), 3), round(float(v['longitude']), 3),
                    ent['labels']['en']['value'], hit['id'])
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-file', help='use a local mledoze countries.json copy')
    ap.add_argument('--regions-only', action='store_true',
                    help='only re-resolve the region list (reuses the current gazetteer.js)')
    args = ap.parse_args()

    if args.regions_only and os.path.exists(OUT):
        prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        places = [p for p in prev['places'] if p.get('t') == 'country']
    else:
        countries = fetch_countries(args.source_file)
        places = []
        for c in countries:
            ll = c.get('latlng') or []
            if len(ll) != 2:
                continue
            places.append({'n': c['name']['common'], 't': 'country',
                           'lat': round(float(ll[0]), 3), 'lng': round(float(ll[1]), 3),
                           # sovereign states outrank their territories when two
                           # entries share an alias ("American" → United States, not
                           # Northern Mariana Islands)
                           'ind': 1 if c.get('independent') else 0,
                           'k': country_keywords(c)})
        print('countries:', len(places), 'keywords:', sum(len(p['k']) for p in places))

    # Resolve region coordinates from sourced geodata, in order of trust:
    # Wikidata P625 (with look-alike rejection) -> Wikipedia coordinates ->
    # OpenStreetMap Nominatim. Every entry records which source it came from.
    wiki = wikipedia_coords([title for _, title, _ in REGIONS])
    kept, dropped = [], []
    for key, title, label in REGIONS:
        src, disp, hit = None, '', None
        wd = wikidata_coords(title)
        if wd:
            hit, src, disp = (wd[0], wd[1]), 'wikidata ' + wd[3], wd[2]
        elif wiki.get(title):
            w = wiki[title]
            hit, src, disp = (w[0], w[1]), 'wikipedia', w[2]
        else:
            try:
                g = geocode(title)
            except Exception as e:
                print('  geocode failed for %s: %s' % (title, e))
                g = None
            time.sleep(2.0)                   # Nominatim usage policy: be gentle
            if g:
                hit, src, disp = (g[0], g[1]), 'osm', g[2]
        if not hit:
            dropped.append(label)
            continue
        kept.append({'n': label, 't': 'region', 'lat': hit[0], 'lng': hit[1],
                     'k': [key], 'src': src, 'ind': 0})
        print('  region %-22s -> %8.3f, %8.3f  [%s] %s' % (label, hit[0], hit[1], src, disp[:60]))
    if dropped:
        print('regions not resolved (left out):', ', '.join(dropped))
    places.extend(kept)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
    header = (
        '// World Monitor — place table for the Live World Signals map / 3D globe.\n'
        '// AUTO-GENERATED by build_gazetteer.py — do not edit by hand.\n'
        '// Countries: mledoze/countries (ISO 3166 names, capitals, demonyms, centroids).\n'
        '// Regions/waterways: OpenStreetMap Nominatim. Curated aliases: build script.\n'
        '// Placement is keyword-derived and country-level: a headline is pinned to the\n'
        '// place it NAMES, never to where the story was sourced. Unplaceable headlines\n'
        '// are simply not plotted. Built ' + stamp + '.\n'
    )
    body = json.dumps({'updated': stamp, 'places': places}, ensure_ascii=False, separators=(',', ':'))
    content = header + 'window.GAZETTEER = ' + body + ';\n'
    prev_content = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else None
    # The date line changes daily; compare payloads so a rebuild with no real change
    # stays a no-op (the cron path must not commit noise).
    if prev_content and prev_content.split('window.GAZETTEER = ', 1)[-1] == content.split('window.GAZETTEER = ', 1)[-1]:
        print('gazetteer unchanged (%d places)' % len(places))
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote %s: %d places (%d countries, %d regions), %d keywords'
          % (OUT, len(places), len(places) - len(kept), len(kept),
             sum(len(p['k']) for p in places)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
