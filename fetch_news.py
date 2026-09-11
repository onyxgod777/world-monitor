#!/usr/bin/env python3
"""fetch_news.py — pull live news RSS/Atom into a committed snapshot (news.js).

The dashboard's Intel feed previously loaded via public CORS proxies from the
browser (allorigins / codetabs / corsproxy.io …), which are rate-limited and
flakey — that made first paint stall on "Contacting…" and feeds vary wildly in
freshness. This scraper fetches the same feed list server-side (where CORS does
not apply — every feed is reachable directly from the server), parses items,
and writes `news.js` (window.NEWS) that the dashboard reads same-origin. It runs
on an interval via the 'World Monitor Intel Feed Snapshot' cron.

app.js consumes this snapshot FIRST (instant, no proxy); if it is absent or
stale it falls back to the old live-proxy fetch. So this file may be a superset
of what renders: app.js applies the existing paywall filter, dedup, 48h recency
cutoff and cap-50 — none of that logic is duplicated here.

Usage:
    python3 fetch_news.py            # write news.js in place (if items changed)
    python3 fetch_news.py --commit   # write + commit + push (only when items changed)
"""
import datetime, json, os, re, subprocess, sys, urllib.request
import xml.etree.ElementTree as ET

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'world-monitor', 'news.js')
REPO = os.path.join(HOME, 'world-monitor')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
      'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*'}

# Mirrors the NEWS_FEEDS list in app.js (region + src labels shown on the cards).
# Keep in sync if app.js changes. URL list is authoritative.
NEWS_FEEDS = [
    {'region': 'World',   'src': 'Google News',     'url': 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en'},
    {'region': 'Markets', 'src': 'Google News',     'url': 'https://news.google.com/rss/search?q=global%20markets%20economy&hl=en-US&gl=US&ceid=US:en'},
    {'region': 'Cyber',   'src': 'Google News',     'url': 'https://news.google.com/rss/search?q=cybersecurity%20hack%20breach&hl=en-US&gl=US&ceid=US:en'},
    {'region': 'Geo',     'src': 'Google News',     'url': 'https://news.google.com/rss/search?q=geopolitics%20diplomacy&hl=en-US&gl=US&ceid=US:en'},
    {'region': 'Energy',  'src': 'Google News',     'url': 'https://news.google.com/rss/search?q=oil%20energy%20commodities&hl=en-US&gl=US&ceid=US:en'},
    {'region': 'World',   'src': 'Al Jazeera',      'url': 'https://www.aljazeera.com/xml/rss/all.xml'},
    {'region': 'World',   'src': 'France 24',       'url': 'https://www.france24.com/en/rss'},
    {'region': 'World',   'src': 'The Conversation','url': 'https://theconversation.com/us/articles.atom'},
    {'region': 'World',   'src': 'Middle East Eye', 'url': 'https://www.middleeasteye.net/rss'},
    {'region': 'World',   'src': 'RFI',             'url': 'https://www.rfi.fr/en/rss'},
    {'region': 'US',      'src': 'ProPublica',      'url': 'https://www.propublica.org/feeds/propublica/main'},
    {'region': 'US',      'src': 'The Intercept',   'url': 'https://theintercept.com/feed/?rss'},
    {'region': 'US',      'src': 'Democracy Now',   'url': 'https://www.democracynow.org/democracynow.rss'},
    {'region': 'US',      'src': 'Reason',          'url': 'https://reason.com/feed/'},
    {'region': 'Climate', 'src': 'Grist',           'url': 'https://grist.org/feed/'},
    {'region': 'Cyber',   'src': '404 Media',       'url': 'https://www.404media.co/rss/'},
    # ── Expanded coverage (every URL below verified reachable with items) ──
    # Europe / Russia / ANZ
    {'region': 'Europe',  'src': 'DW',               'url': 'https://rss.dw.com/rdf/rss-en-all'},
    {'region': 'Europe',  'src': 'The Guardian',     'url': 'https://www.theguardian.com/world/rss'},
    {'region': 'Europe',  'src': 'El País',          'url': 'https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada'},
    {'region': 'Europe',  'src': 'Meduza',           'url': 'https://meduza.io/rss/en/all'},
    {'region': 'Europe',  'src': 'The Moscow Times', 'url': 'https://www.themoscowtimes.com/rss/news'},
    {'region': 'Europe',  'src': 'TASS',             'url': 'https://tass.com/rss/v2.xml'},
    {'region': 'Europe',  'src': 'CBC World',        'url': 'https://www.cbc.ca/webfeed/rss/rss-world'},
    {'region': 'Europe',  'src': 'ABC Australia',    'url': 'https://www.abc.net.au/news/feed/51120/rss.xml'},
    {'region': 'World',   'src': 'NPR',              'url': 'https://feeds.npr.org/1004/rss.xml'},
    # Middle East / South & East Asia / Africa
    {'region': 'Mideast', 'src': 'Times of Israel',  'url': 'https://www.timesofisrael.com/feed/'},
    {'region': 'Mideast', 'src': 'Al-Monitor',       'url': 'https://www.al-monitor.com/rss'},
    {'region': 'Mideast', 'src': 'Tehran Times',     'url': 'https://www.tehrantimes.com/rss'},
    {'region': 'Mideast', 'src': 'Anadolu Agency',   'url': 'https://www.aa.com.tr/en/rss/default?cat=guncel'},
    {'region': 'Asia',    'src': 'Dawn',             'url': 'https://www.dawn.com/feeds/home'},
    {'region': 'Asia',    'src': 'Channel NewsAsia', 'url': 'https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml'},
    {'region': 'Asia',    'src': 'Bangkok Post',     'url': 'https://www.bangkokpost.com/rss/data/topstories.xml'},
    {'region': 'Africa',  'src': 'Premium Times',    'url': 'https://www.premiumtimesng.com/feed'},
    # Humanitarian / disaster / health — these also feed the World map
    {'region': 'Disaster','src': 'ReliefWeb',        'url': 'https://reliefweb.int/updates/rss.xml'},
    {'region': 'Disaster','src': 'GDACS',            'url': 'https://www.gdacs.org/xml/rss.xml'},
    {'region': 'Disaster','src': 'FloodList',        'url': 'https://floodlist.com/feed'},
    {'region': 'Disaster','src': 'Smithsonian GVP',  'url': 'https://volcano.si.edu/news/WeeklyVolcanoRSS.xml'},
    {'region': 'Health',  'src': 'WHO',              'url': 'https://www.who.int/rss-feeds/news-english.xml'},
    {'region': 'World',   'src': 'UN News',          'url': 'https://news.un.org/feed/subscribe/en/news/all/rss.xml'},
    # Security / cyber incident reporting
    {'region': 'Security','src': 'Bellingcat',       'url': 'https://www.bellingcat.com/feed/'},
    {'region': 'Security','src': 'The Record',       'url': 'https://therecord.media/feed'},
    {'region': 'Cyber',   'src': 'Krebs on Security','url': 'https://krebsonsecurity.com/feed/'},
    {'region': 'Cyber',   'src': 'BleepingComputer', 'url': 'https://www.bleepingcomputer.com/feed/'},
    {'region': 'Cyber',   'src': 'CISA Advisories',  'url': 'https://www.cisa.gov/cybersecurity-advisories/all.xml'},
    {'region': 'Cyber',   'src': 'SANS ISC',         'url': 'https://isc.sans.edu/rssfeed.xml'},
    # Energy / shipping / climate / space
    {'region': 'Energy',  'src': 'OilPrice',         'url': 'https://oilprice.com/rss/main'},
    {'region': 'Energy',  'src': 'gCaptain',         'url': 'https://gcaptain.com/feed/'},
    {'region': 'Climate', 'src': 'Carbon Brief',     'url': 'https://www.carbonbrief.org/feed'},
    {'region': 'Space',   'src': 'Spaceflight Now',  'url': 'https://spaceflightnow.com/feed/'},
    {'region': 'Space',   'src': 'NASA',             'url': 'https://www.nasa.gov/rss/dyn/breaking_news.rss'},
    {'region': 'FIGU',    'src': 'They Fly Blog',    'url': 'https://theyflyblog.com/feed/'},
]
# Non-<item> Atom namespaces declare their own pubdate tags; we strip namespaces
# so <published>/<updated> are reachable regardless of ns prefix.
RSS_NS = '{http://www.w3.org/2005/Atom}'

# Topic noise. The expanded outlet list includes general-interest home feeds (for
# example Dawn's), whose front page carries sport and showbiz alongside world
# news. Those items are real, just not intelligence — drop them here so the panel
# stays an intel board. Deliberately narrow: only unambiguous non-intel beats.
NOISE_RE = re.compile(
    r'\b(cricket|football|soccer|nba|nfl|nhl|mlb|tennis|golf|olympics?|ipl|'
    r'box office|celebrity|horoscope|astrology|beauty pageant|recipe|'
    r'movie review|tv review|royal wedding)\b', re.I)


def is_noise(title):
    """True for items we never want on an intelligence board: junk/short titles
    (bare numbers, nav text) and unambiguous sport/showbiz filler."""
    t = (title or '').strip()
    if len(t) < 18:
        return True
    if re.fullmatch(r'[\d\s.,%:/\-–—]+', t):
        return True
    return bool(NOISE_RE.search(t))


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode('utf-8', 'ignore')

def clean(s):
    if not s: return ''
    s = s.replace('&#8217;', "'").replace('&#8211;', '–').replace('&#8212;', '—')
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', s).strip()

def to_epoch(pub):
    """Any feed date -> epoch ms (UTC). Returns 0 if unparseable (ranked oldest)."""
    if not pub: return 0
    p = clean(pub)
    for fmt in ('%a, %d %b %Y %H:%M:%S %Z', '%a, %d %b %Y %H:%M:%S %z',
                '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S', '%d %b %Y %H:%M:%S'):
        try:
            dt = datetime.datetime.strptime(p, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return 0

def strip_ns(tag):
    return tag[tag.rfind('}')+1:] if '}' in tag else tag

def split_title_source(title, source):
    """If a title ends ' — Outlet' / ' - Outlet' and no source tag was given,
    lift the outlet off the title (matches app.js behaviour)."""
    if source or not title:
        return title, source
    m = re.search(r'\s(?:—|-|–)\s+([^-—–]+?)\s*$', title)
    if m and len(m.group(1)) < 60:
        return title[:m.start()].strip(), m.group(1).strip()
    return title, source

def parse_xml(text):
    """Parse an RSS (<item>) or Atom (<entry>) document -> list of raw items."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    container = root.find('.//channel')
    if container is None:   # Atom feeds have no <channel>; items sit at the root
        container = root
    for node in container:
        tag = strip_ns(node.tag)
        if tag not in ('item', 'entry'):
            continue
        g = lambda *names: clean(' '.join(x.text or '' for x in node.iter() if strip_ns(x.tag) in names))
        title = g('title')
        link = ''
        for l in node.iter():
            if strip_ns(l.tag) == 'link':
                if l.get('href'): link = l.get('href')
                elif l.text: link = clean(l.text)
                if link: break
        pub = g('pubDate', 'published', 'updated', 'date')
        source = g('source', 'creator', 'author', 'dc:creator')
        title, source = split_title_source(title, source)
        if not title:
            continue
        out.append({'title': title, 'source': source, 'link': link,
                    'ts': to_epoch(pub)})
    return out

def main():
    items = []
    src_ok = 0
    verbose = '--verbose' in sys.argv
    for f in NEWS_FEEDS:
        try:
            text = fetch(f['url'])
            parsed = parse_xml(text)
        except Exception as e:
            parsed = []   # a dead feed must not kill the pass
            if verbose:
                print('  DEAD  %-18s %s' % (f['src'], str(e)[:60]))
        parsed = [p for p in parsed if not is_noise(p['title'])]
        if parsed:
            src_ok += 1
        elif verbose:
            print('  EMPTY %-18s %s' % (f['src'], f['url'][:60]))
        for it in parsed:
            it['region'] = f['region']
            it['src'] = f['src']
        items.extend(parsed)
    if not items:
        print('parsed 0 items across %d feeds — aborting to avoid clobbering' % len(NEWS_FEEDS))
        sys.exit(1)
    # Dedup by normalized title, keep the first (feed order) occurrence.
    seen = set(); uniq = []
    for it in items:
        k = (it['title'] or '').lower().strip()
        if not k or k in seen:
            continue
        seen.add(k); uniq.append(it)
    # Drop near-duplicates (Google News repeats the same story under many
    # outlets): normalize to lowercase alphanumerics and keep one per title-core.
    dedup2 = {}
    for it in uniq:
        core = re.sub(r'[^a-z0-9 ]', '', (it['title'] or '').lower())
        if core not in dedup2:
            dedup2[core] = it
    uniq = list(dedup2.values())
    uniq.sort(key=lambda x: -x['ts'])   # newest first
    # Per-source quotas before the global cut. Sorting by recency alone starves
    # low-volume outlets: the Google News wire posts ~100 items/day, so a blog
    # that posts twice a week never survives a flat newest-N slice and vanishes
    # from the panel entirely. Every working source therefore gets a FLOOR of its
    # two newest items reserved before the recency cut, then up to PER_FEED_CAP
    # more compete for the remaining slots. app.js applies the 48h cutoff, its own
    # balanced selection and cap on top of this superset.
    PER_FEED_FLOOR, PER_FEED_CAP, SNAPSHOT_CAP = 2, 8, 240
    per_src = {}
    for it in uniq:
        per_src.setdefault(it['src'], []).append(it)
    floor = [it for lst in per_src.values() for it in lst[:PER_FEED_FLOOR]]
    reserved = {(i['title'], i['ts']) for i in floor}
    rest = [it for lst in per_src.values() for it in lst[PER_FEED_FLOOR:PER_FEED_CAP]
            if (it['title'], it['ts']) not in reserved]
    rest.sort(key=lambda x: -x['ts'])
    budget = max(0, SNAPSHOT_CAP - len(floor))
    uniq = floor + rest[:budget]
    uniq.sort(key=lambda x: -x['ts'])
    if verbose:
        print('  kept %d items from %d sources (floor %d)' % (len(uniq), len(per_src), len(floor)))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {'_updated': stamp, 'sources': '%d/%d feeds' % (src_ok, len(NEWS_FEEDS)),
            'items': uniq}
    content = ('// AUTO-GENERATED by fetch_news.py — do not edit by hand.\n'
               '// Live Intel feed snapshot, fetched server-side (no CORS proxy).\n'
               'window.NEWS = ' + json.dumps(data, ensure_ascii=False) + ';\n')
    # Change detection: compare only the items (title+link+ts), so an unchanged
    # headline set doesn't spam git even though the _updated stamp ticks.
    def sig(t):
        return json.dumps([(i['title'], i['ts']) for i in t.get('items', [])])
    prev_items = []
    if os.path.exists(OUT):
        try:
            prev_items = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0]).get('items', [])
        except Exception:
            prev_items = []
    if sig({'items': uniq}) == sig({'items': prev_items}):
        print('news.js unchanged (%d items, %s, %s)' % (len(uniq), data['sources'], stamp))
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote news.js: %d items, %s, %s' % (len(uniq), data['sources'], stamp))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'news.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'intel: news feed snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0

if __name__ == '__main__':
    sys.exit(main())
