#!/usr/bin/env python3
"""fetch_social.py — pull public Telegram, Reddit and X/Twitter signals into social.js.

Sources are all *public, keyless* surfaces, fetched server-side (no CORS in the way):

  TELEGRAM  https://t.me/s/<channel>            public channel preview pages (HTML)
  REDDIT    https://www.reddit.com/r/a+b+c/new/.rss   public Atom feed, many subs per request
  X/TWITTER https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>
            Twitter's own public timeline widget endpoint (the thing that renders
            embedded profile timelines). Keyless, but per-handle CACHED — a handle
            whose widget cache is old simply contributes nothing, so everything is
            freshness-gated below. We never present a cached tweet as new.

Honesty rules baked in:
  * Every item carries `platform` and the panel labels it (TELEGRAM / REDDIT / X).
    These are first-report/unverified social signals, not edited journalism.
  * Telegram text is truncated and links back to the public post; Reddit links to
    the thread; X links to the post on x.com.
  * A source that yields nothing is dropped, never faked.

Usage:
    python3 fetch_social.py            # write social.js in place (if changed)
    python3 fetch_social.py --commit   # write + commit + push (only when changed)
"""
import concurrent.futures, datetime, html, json, os, re, subprocess, sys, time
import urllib.error, urllib.request

HOME = os.path.expanduser('~')
OUT = os.path.join(HOME, 'world-monitor', 'social.js')
REPO = os.path.join(HOME, 'world-monitor')
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9'}

HOUR = 3600 * 1000
TG_MAX_AGE = 72 * HOUR        # channel previews: keep the last few days
RD_MAX_AGE = 48 * HOUR        # reddit threads move fast
X_MAX_AGE = 7 * 24 * HOUR     # x widget caches vary wildly; 7d keeps the honest ones
TG_PER_CH, RD_PER_SUB, X_PER_HANDLE = 6, 4, 5

# ── Telegram: public channels with working t.me/s previews (verified reachable) ──
# region is always TELEGRAM so the panel labels the platform explicitly; the
# channel label carries the outlet identity.
TELEGRAM = [
    ('intelslava',       'Intel Slava',        'TELEGRAM'),
    ('rybar',            'Rybar',              'TELEGRAM'),
    ('nexta_tv',         'NEXTA',              'TELEGRAM'),
    ('DeepStateUA',      'DeepState UA',       'TELEGRAM'),
    ('UNITED24media',    'UNITED24',           'TELEGRAM'),
    ('UkraineNow',       'Ukraine Now',        'TELEGRAM'),
    ('wartranslated',    'War Translated',     'TELEGRAM'),
    ('ClashReport',      'Clash Report',       'TELEGRAM'),
    ('DDGeopolitics',    'DD Geopolitics',     'TELEGRAM'),
]
# ── Reddit: one request per combo keeps us far under the public rate limit ──
REDDIT_COMBOS = [
    ['worldnews', 'geopolitics', 'ukraine', 'CredibleDefense', 'europe'],
    ['OSINT', 'cybersecurity', 'energy', 'economics', 'Climate', 'intelligence'],
    ['Military', 'china', 'india', 'africa', 'MiddleEastNews'],
]
# ── X/Twitter handles (public syndication widget) ──
X_HANDLES = [
    'sentdefender', 'nexta_tv', 'KyivIndependent', 'AP', 'NWS', 'USGS', 'ClashReport',
    'bellingcat', 'GeoConfirmed', 'OSINTtechnical', 'Faytuks', 'wartranslated',
    'Tendar', 'NOELreports', 'IntelRepublic', 'DDGeopolitics',
]
# handles are case-insensitive on the wire; keep one casing per account
_seen_h = set()
X_HANDLES = [h for h in X_HANDLES if not (h.lower() in _seen_h or _seen_h.add(h.lower()))]


def get(url, timeout=25, ua=None):
    req = urllib.request.Request(url, headers=ua or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def clean(s):
    if not s:
        return ''
    s = re.sub(r'<br\s*/?>', ' ', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(html.unescape(s))
    s = s.replace('\u200b', '').replace('\u2060', '')
    return re.sub(r'\s+', ' ', s).strip()


def now_ms():
    return int(time.time() * 1000)


# Same narrow topic filter as fetch_news.py: reddit front pages carry sport and
# showbiz alongside the security/geopolitics beats we want here.
NOISE_RE = re.compile(
    r'\b(cricket|football|soccer|nba|nfl|nhl|mlb|tennis|golf|olympics?|ipl|'
    r'box office|celebrity|horoscope|astrology|beauty pageant|recipe)\b', re.I)


def is_noise(title):
    t = (title or '').strip()
    if len(t) < 18 or re.fullmatch(r'[\d\s.,%:/\-–—]+', t):
        return True
    return bool(NOISE_RE.search(t))


# ────────────────────────── TELEGRAM ──────────────────────────
def fetch_telegram(ch):
    name, label, region = ch
    try:
        body = get('https://t.me/s/' + name)
    except Exception as e:
        return ('telegram', name, [], str(e)[:60])
    out, cut = [], now_ms() - TG_MAX_AGE
    # Each post is a data-post block; take text + timestamp from within it.
    for post, blk in re.findall(r'data-post="([^"]+)"(.*?)(?=data-post="|$)', body, re.S):
        t = re.search(r'<time datetime="([^"]+)"', blk)
        if not t:
            continue
        try:
            ts = int(datetime.datetime.strptime(t.group(1)[:19], '%Y-%m-%dT%H:%M:%S')
                     .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        except Exception:
            continue
        if ts < cut:
            continue
        m = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', blk, re.S)
        text = clean(m.group(1)) if m else ''
        if len(text) < 12:                      # media-only / sticker-only posts
            continue
        out.append({'title': text[:280], 'source': '@' + name, 'link': 'https://t.me/' + post,
                    'ts': ts, 'region': region, 'src': label, 'platform': 'TELEGRAM'})
    out = sorted(out, key=lambda x: -x['ts'])[:TG_PER_CH]
    return ('telegram', name, out, '')


# ────────────────────────── REDDIT ──────────────────────────
def fetch_reddit(combo):
    url = 'https://www.reddit.com/r/%s/new/.rss?limit=25' % '+'.join(combo)
    err = ''
    for attempt in range(4):
        try:
            body = get(url, timeout=25)
            out = []
            cut = now_ms() - RD_MAX_AGE
            for e in re.findall(r'<entry>(.*?)</entry>', body, re.S):
                title = clean((re.search(r'<title>(.*?)</title>', e, re.S) or [None, ''])[1])
                link = ''
                lm = re.search(r'<link[^>]*href="([^"]+)"', e)
                if lm:
                    link = lm.group(1)
                um = re.search(r'<updated>(.*?)</updated>', e, re.S)
                if not title or not um or is_noise(title):
                    continue
                try:
                    ts = int(datetime.datetime.strptime(um.group(1)[:19], '%Y-%m-%dT%H:%M:%S')
                             .replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
                except Exception:
                    continue
                if ts < cut:
                    continue
                sm = re.search(r'/r/([A-Za-z0-9_]+)/', link)
                sub = sm.group(1) if sm else 'reddit'
                out.append({'title': title[:280], 'source': '/r/' + sub, 'link': link,
                            'ts': ts, 'region': 'REDDIT', 'src': 'r/' + sub, 'platform': 'REDDIT'})
            return ('reddit', '+'.join(combo), out, '')
        except urllib.error.HTTPError as e:
            err = 'HTTP %s' % e.code
            if e.code == 429:
                wait = int(e.headers.get('Retry-After') or 0) or (6 + attempt * 6)
                time.sleep(min(wait, 30))
                continue
            break
        except Exception as e:
            err = str(e)[:60]
            break
    return ('reddit', '+'.join(combo), [], err)


# ────────────────────────── X / TWITTER ──────────────────────────
def _walk_tweets(o, acc):
    if isinstance(o, dict):
        if isinstance(o.get('full_text'), str) and o.get('created_at'):
            acc.append(o)
        for v in o.values():
            _walk_tweets(v, acc)
    elif isinstance(o, list):
        for v in o:
            _walk_tweets(v, acc)


def fetch_x(handle):
    try:
        body = get('https://syndication.twitter.com/srv/timeline-profile/screen-name/' + handle, timeout=30)
    except Exception as e:
        return ('x', handle, [], str(e)[:60])
    nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', body, re.S)
    if not nd:
        return ('x', handle, [], 'no timeline payload')
    try:
        data = json.loads(nd.group(1))
    except Exception:
        return ('x', handle, [], 'bad timeline payload')
    raw = []
    _walk_tweets(data, raw)
    cut, seen, out = now_ms() - X_MAX_AGE, set(), []
    for t in raw:
        try:
            ts = int(datetime.datetime.strptime(t['created_at'], '%a %b %d %H:%M:%S %z %Y').timestamp() * 1000)
        except Exception:
            continue
        if ts < cut:
            continue
        tid = str(t.get('id_str') or t.get('id') or '')
        text = clean(t.get('full_text') or '')
        if not tid or tid in seen or len(text) < 12 or NOISE_RE.search(text):
            continue
        seen.add(tid)
        out.append({'title': text[:280], 'source': '@' + handle,
                    'link': 'https://x.com/%s/status/%s' % (handle, tid),
                    'ts': ts, 'region': 'X', 'src': '@' + handle, 'platform': 'X'})
    out = sorted(out, key=lambda x: -x['ts'])[:X_PER_HANDLE]
    return ('x', handle, out, '')


def load_prev():
    """Previous snapshot items, for carry-forward when a source is unreachable
    this pass. A flaky pass must not silently drop a whole platform from the
    dashboard — stale-but-labelled beats blank."""
    if not os.path.exists(OUT):
        return []
    try:
        d = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        return d.get('items') or []
    except Exception:
        return []


def main():
    prev_items = load_prev()
    results, items, notes = [], [], {}
    # Telegram + X are independent hosts => modest parallel fetch. Reddit is
    # serialised (single host, aggressive 429s) and spaced out. The combo order
    # rotates with the hour so a rate-limited tail never starves the same subs.
    combos = REDDIT_COMBOS
    if combos:
        k = datetime.datetime.now(datetime.timezone.utc).hour % len(combos)
        combos = combos[k:] + combos[:k]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_telegram, c) for c in TELEGRAM]
        futs += [ex.submit(fetch_x, h) for h in X_HANDLES]
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception:
                pass
    for combo in combos:
        try:
            results.append(fetch_reddit(combo))
        except Exception as e:
            results.append(('reddit', '+'.join(combo), [], str(e)[:60]))
        time.sleep(8)

    # platform -> age window for carry-forward
    window = {'telegram': TG_MAX_AGE, 'reddit': RD_MAX_AGE, 'x': X_MAX_AGE}
    cut = now_ms()
    for kind, name, got, err in results:
        notes.setdefault(kind, {'ok': 0, 'empty': [], 'carried': []})
        if not got:
            # carry the previous snapshot's items for exactly this source
            subs = ['r/' + s for s in name.split('+')] if kind == 'reddit' else None
            keep = [i for i in prev_items
                    if i.get('platform') == kind.upper()
                    and (subs is None or i.get('src') in subs)
                    and (subs is not None or name.lower() in (i.get('link') or '').lower()
                         or i.get('source', '').lstrip('@').lower() == name.lower())
                    and (cut - int(i.get('ts') or 0)) <= window.get(kind, RD_MAX_AGE)]
            if keep:
                notes[kind]['carried'].append(name)
                items.extend(keep)
            else:
                notes[kind]['empty'].append(name)
            continue
        notes[kind]['ok'] += 1
        items.extend(got)
    if not items:
        print('parsed 0 social items and nothing to carry — aborting to avoid clobbering')
        sys.exit(1)
    # dedup by link, newest first, then per-platform quota so no platform (or
    # handle) monopolises the snapshot.
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: -x['ts']):
        if it['link'] in seen:
            continue
        seen.add(it['link'])
        uniq.append(it)
    per_src, cap = {}, {'TELEGRAM': 40, 'REDDIT': 45, 'X': 45}
    kept = []
    for it in uniq:
        k = it['src']
        if per_src.get(k, 0) >= 6:              # max 6 per channel/outlet
            continue
        if sum(1 for x in kept if x['platform'] == it['platform']) >= cap[it['platform']]:
            continue
        per_src[k] = per_src.get(k, 0) + 1
        kept.append(it)
    kept.sort(key=lambda x: -x['ts'])
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    data = {
        '_updated': stamp,
        'note': 'Public, keyless social signals — first reports, unverified. Telegram = public '
                'channel previews; Reddit = public Atom feeds; X = Twitter public timeline widget '
                '(per-handle cached, stale handles contribute nothing).',
        'methods': {'telegram': 't.me/s public previews', 'reddit': 'www.reddit.com/r/*/new/.rss',
                    'x': 'syndication.twitter.com timeline-profile'},
        'counts': {k: sum(1 for i in kept if i['platform'] == k.upper()) for k in ('telegram', 'reddit', 'x')},
        'sources': notes,
        'items': kept,
    }
    content = ('// AUTO-GENERATED by fetch_social.py — do not edit by hand.\n'
               '// Public Telegram / Reddit / X signals (keyless, freshness-gated).\n'
               'window.SOCIAL = ' + json.dumps(data, ensure_ascii=False) + ';\n')

    def sig(d):
        return json.dumps([(i['link'], i['ts']) for i in d.get('items', [])])
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        except Exception:
            prev = {}
    if sig(data) == sig(prev):
        print('social.js unchanged (%d items, %s)' % (len(kept), stamp))
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote social.js: %d items %s' % (len(kept), data['counts']))
    for k, v in notes.items():
        print('  %-9s ok=%-3d carried=%-2d empty=%s' %
              (k, v['ok'], len(v['carried']), ','.join(v['empty'][:8]) or '-'))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'social.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'social: telegram/reddit/x signal snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
