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
    {'region': 'FIGU',    'src': 'They Fly Blog',   'url': 'https://theyflyblog.com/feed/'},
]
# Non-<item> Atom namespaces declare their own pubdate tags; we strip namespaces
# so <published>/<updated> are reachable regardless of ns prefix.
RSS_NS = '{http://www.w3.org/2005/Atom}'

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
    for f in NEWS_FEEDS:
        try:
            text = fetch(f['url'])
            parsed = parse_xml(text)
        except Exception:
            parsed = []   # a dead feed must not kill the pass
        if parsed:
            src_ok += 1
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
    # Per-source quota before the global cut. Sorting by recency alone starves
    # low-volume outlets: the Google News wire posts ~100 items/day, so a blog
    # that posts twice a week never survives a flat newest-N slice and vanishes
    # from the panel entirely. Keep the newest PER_FEED_CAP per source, then the
    # newest SNAPSHOT_CAP overall — app.js applies the 48h cutoff, its own
    # balanced selection and cap on top of this superset.
    PER_FEED_CAP, SNAPSHOT_CAP = 12, 80
    per_src = {}
    for it in uniq:
        per_src.setdefault(it['src'], []).append(it)
    kept = [it for lst in per_src.values() for it in lst[:PER_FEED_CAP]]
    kept.sort(key=lambda x: -x['ts'])
    uniq = kept[:SNAPSHOT_CAP]
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
