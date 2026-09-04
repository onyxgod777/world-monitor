#!/usr/bin/env python3
"""
sync_prophecies.py — regenerate World Monitor's prophecies.js from the
News & Prophecy page source.

Source of truth: /home/kali/tvop.github.io/docs/news/index.md (the markdown the
daily News & Prophecy job publishes to pi.thealpha-secret.xyz/news/).
Output:         /home/kali/world-monitor/prophecies.js (embedded in the Prophecy
                tab of worldmonitor.thealpha-secret.xyz).

Every field on each prophecy card is derived deterministically from the
published markdown so the dashboard always mirrors the page with no hand-edited
JSON to drift. Run this after the News & Prophecy page updates, then commit +
push the world-monitor repo. idempotent: safe to run any time.

Usage: python3 sync_prophecies.py            # regenerate in place
       python3 sync_prophecies.py --commit    # regenerate, commit, push
"""
import os, re, sys, subprocess, json

HOME = os.path.expanduser('~')
SRC = os.path.join(HOME, 'tvop.github.io', 'docs', 'news', 'index.md')
OUT = os.path.join(HOME, 'world-monitor', 'prophecies.js')
REPO = os.path.join(HOME, 'world-monitor')

def clean(s):
    return re.sub(r'\s+', ' ', s).strip()

# --- parse the markdown into the 5 story sections -----------------------------
def parse_stories(txt):
    segs = [s for s in re.split(r'\n(?=### )', txt) if s.strip()]
    out = []
    for seg in segs:
        if not seg.startswith('### '):
            continue
        headline = clean(seg.split('\n', 1)[0].lstrip('# '))
        body = seg.split('\n', 1)[1]
        dm = re.search(r'\?\?\?\+ danger "([^"]*)"\n(.*?)(?=\n\?\?\? warning |\n---|\Z)', body, re.S)
        cause = clean(dm.group(2)) if dm else ''
        wm = re.search(r'\?\?\? warning "([^"]*)"\n(.*?)(?=\n---|\Z)', body, re.S)
        warn_title, bullets, verse, verse_src, hinge = '', [], '', '', ''
        if wm:
            warn_title = clean(wm.group(1))
            wb = wm.group(2)
            bullets = [clean(b) for b in re.findall(r'^ {4}- (.*)$', wb, re.M)]
            vq = re.search(r'^\s*\*"(.*?)"\*\s*[—–-]\s*\*[^*]*\*,\s*(Chapter\s+\d+,\s*Verse\s+\d+)', wb, re.M)
            if vq:
                verse = clean(vq.group(1)); verse_src = clean(vq.group(2))
            else:  # §-style citation (no chapter/verse form)
                v2 = re.search(r'^\s*\*"(.*?)"\*\s*[—–-]\s*\*([^*§]+(?:\u00a7[0-9–-]+)*)\*', wb, re.M)
                if v2:
                    verse = clean(v2.group(1)); verse_src = clean(v2.group(2))
            hg = re.search(r'\*\*The hinge:\*\*\s*(.*?)(?=\n\s*$|\n---|\Z)', wb, re.S)
            hinge = clean(hg.group(1)) if hg else ''
        out.append({'headline': headline, 'cause': cause, 'warn_title': warn_title,
                    'bullets': bullets, 'verse': verse, 'verse_src': verse_src, 'hinge': hinge})
    return out

# --- domain classification (headline topics -> tag / color) -------------------
# Order matters: specific conflict/region domains are checked BEFORE the broad
# markets/climate catch-alls, and classification uses the headline text only
# (the cause paragraph is too wordy and drags every story toward generic tags).
DOMAINS = [
    (r'cyber|hack|breach|ransom|zero[- ]day',       'CYBER · SECURITY',    'amber'),
    (r'ukraine|kyiv|russian airspace|airspace|airline|zelen|putin',
        'CONFLICT · AIRSPACE', 'red'),
    (r'iran|tehran|hormuz|kuwait|uae|gulf|iraq|ceasefire',
        'SECURITY · GEOPOLITICS', 'red'),
    (r'israel|west bank|settlement|jenin|palestin|gaza|netanyahu',
        'WEST BANK · JUSTICE', 'red'),
    (r'el nino|enso|climate|warming|drought|wildfire|flood|storm|typhoon|hurricane|1\.5',
        'CLIMATE · WEATHER', 'amber'),
    (r'bond|yield|treasury|rate|inflation|central bank|fed|debt|gold|markets?|sell-off',
        'MARKETS · RATES',  'amber'),
]
# keyword pools per tag for the live feed-coverage counter (matched against live headlines)
KW_POOL = {
    'CYBER · SECURITY':      ['cyber', 'hack', 'breach', 'ransom', 'zero-day'],
    'CONFLICT · AIRSPACE':   ['ukraine', 'kyiv', 'russia', 'moscow', 'airline', 'airspace'],
    'SECURITY · GEOPOLITICS':['iran', 'tehran', 'hormuz', 'kuwait', 'uae', 'gulf', 'iraq', 'ceasefire'],
    'WEST BANK · JUSTICE':   ['israel', 'west bank', 'settlement', 'jenin', 'palestinian', 'gaza'],
    'CLIMATE · WEATHER':     ['el nino', 'climate', 'storm', 'drought', 'weather', 'flood', 'wildfire'],
    'MARKETS · RATES':       ['bond', 'yield', 'treasury', 'fed', 'rate', 'inflation', 'gold', 'debt', 'market'],
}
def classify(title):
    blob = title.lower()
    for rx, tag, cls in DOMAINS:
        if re.search(rx, blob):
            return tag, cls
    return 'GEOPOLITICS · SIGNAL', 'red'

def split_emoji_title(headline):
    # headline starts with a flag emoji token
    m = re.match(r'^(\S+)\s+(.*)$', headline, re.S)
    if m:
        return m.group(1), m.group(2).strip()
    return '', headline

def make_short(title):
    # concise one-line display title: strip any leading "Region: " label, then cut
    # at the first hard break (a ' — ' em dash or a standalone ':') to keep a tidy
    # clause; fall back to a word-boundary truncation for long run-on titles.
    t = title
    # drop a leading "Region: " / "Region, x: " preamble so the label isn't the whole line
    m = re.match(r'^([^:]{2,60}?):\s*(.{20,})$', t)
    if m:
        t = m.group(2)
    # cut at first em-dash sentence break if the remainder is still long
    if ' — ' in t:
        head = t.split(' — ', 1)[0]
        if len(head) >= 40:
            return head.rstrip()
    # word-boundary truncation cap
    if len(t) > 150:
        cut = t[:150]
        sp = cut.rfind(' ')
        return (cut[:sp] if sp > 60 else cut).rstrip() + '…'
    return t.rstrip()

def build_record(s):
    emoji, title = split_emoji_title(s['headline'])
    tag, cls = classify(title)
    return {
        'emoji': emoji,
        'title': title,
        'short': make_short(title) or title,
        'tag': tag,
        'cls': cls,
        'kw': KW_POOL.get(tag, []),
        'cause': s['cause'],
        'bullets': s['bullets'],
        'verse': s['verse'],
        'verseSrc': s['verse_src'] or 'Goblet of the Truth',
        'hinge': s['hinge'],
    }

def updated_date(txt):
    m = re.search(r'\*Updated\s+(\d{4}-\d{2}-\d{2})\*', txt)
    return m.group(1) if m else __import__('datetime').date.today().isoformat()

def main():
    if not os.path.exists(SRC):
        print('SRC not found:', SRC); sys.exit(1)
    txt = open(SRC, encoding='utf-8').read()
    stories = parse_stories(txt)
    if len(stories) < 1:
        print('no stories parsed from', SRC); sys.exit(1)
    records = [build_record(s) for s in stories]
    date = updated_date(txt)
    header = (
        '// World Monitor — Prophecy data file (News & Prophecy causal analyses).\n'
        '// Source: https://pi.thealpha-secret.xyz/news/  ·  Updated ' + date + '\n'
        '// AUTO-GENERATED by sync_prophecies.py — do not edit by hand.\n'
    )
    payload = json.dumps(records, ensure_ascii=False, indent=1)
    content = header + 'const PROPHECIES = ' + payload + ';\n\n' \
        + "PROPHECIES._updated = '" + date + "';\n"
    # skip write if unchanged
    prev = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
    if prev == content:
        print('prophecies.js unchanged (' + str(len(records)) + ' stories, updated ' + date + ')')
        return 0
    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote prophecies.js:', len(records), 'stories, updated', date)
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'prophecies.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'news: sync prophecies.js from News & Prophecy (%s)' % date], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0

if __name__ == '__main__':
    sys.exit(main())
