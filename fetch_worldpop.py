#!/usr/bin/env python3
"""fetch_worldpop.py — snapshot the FIGU world-population data into worldpop.js.

Primary source: https://ca.figu.org/overpopulation.html
That page publishes the population scans and a live counter. Everything the
dashboard shows comes straight off it:
  * the scan series (20 points, 2004-04-08 -> the latest scan) from the page's own
    `var epochs = new Array(...)` / `var populations = new Array(...)` block —
    the same arrays the FIGU site's counter evaluates;
  * the headline sentence ("As of <date> ... exactly <N> or an increase of <M>
    since last year!");
  * the Goblet of the Truth extent the page quotes (529 million human beings).
The card then evaluates a Lagrange quadratic through the last three scans at the
current instant, which is exactly what the FIGU page's own counter does (their
`calculate()` builds the same coefficients from `epochs[n-3..n-1]`).

The World Bank/UN figure is fetched too, purely as a labelled cross-check, because
the two sources differ by well over a billion people and the card states that
rather than hiding it.

Never guesses: if the page's arrays cannot be read, worldpop.js is left untouched.
"""
import datetime, json, os, re, subprocess, sys, urllib.request

HOME = os.path.expanduser('~')
REPO = os.environ.get('WM_REPO_DIR') or os.path.join(HOME, 'world-monitor')
OUT = os.path.join(REPO, 'worldpop.js')
FIGU_URL = 'https://ca.figu.org/overpopulation.html'
WB_API = 'https://api.worldbank.org/v2/country/WLD/indicator/%s?format=json&date=2015:2035&per_page=40'
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36',
      'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8'}


def get(url, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def parse_figu(html):
    """Return the page's scan series + headline + Goblet extent, or raise."""
    # The page separates numbers from words with &nbsp; in the live sentence, which the
    # regexes would read as part of the number, so normalise entities first.
    html = html.replace('&nbsp;', ' ').replace('\u00a0', ' ').replace('\u2019', "'")
    html = __import__('html').unescape(html)

    def arr(name):
        m = re.search(r'var\s+%s\s*=\s*new\s+Array\(([^)]+)\)' % name, html)
        if not m:
            m = re.search(r'var\s+%s\s*=\s*\(([^)]+)\)' % name, html)
        if not m:
            raise ValueError('array %s not found' % name)
        return [int(x.strip()) for x in m.group(1).split(',') if x.strip()]

    epochs, pops = arr('epochs'), arr('populations')
    if len(epochs) != len(pops) or len(epochs) < 3:
        raise ValueError('series mismatch: %d epochs vs %d populations' % (len(epochs), len(pops)))
    if any(e < 9e8 or p < 1e9 for e, p in zip(epochs, pops)):
        raise ValueError('implausible value in the series')

    head = {}
    # The page carries more than one such sentence (the current one, plus older ones in
    # meta/description text), so collect them all and keep the one that matches the last
    # scan in the series — the two must never be able to disagree.
    strip = lambda s: int(re.sub(r'\D', '', s))
    cands = []
    for m in re.finditer(r'As of\s+(.+?)\s+the population on our planet was exactly\s*([\d,\u2019\.]+)\s*'
                         r'or an increase of\s*([\d,\u2019\.]+)(\s+[A-Za-z][^!<]{0,30})?', html, re.I | re.S):
        cands.append({'dateText': re.sub(r'\s+', ' ', m.group(1)).strip().rstrip(','),
                      'value': strip(m.group(2)), 'increase': strip(m.group(3)),
                      'quote': 'As of %s the population on our planet was exactly %s or an increase of %s%s!' % (
                          re.sub(r'\s+', ' ', m.group(1)).strip().rstrip(','), m.group(2).strip(),
                          m.group(3).strip(), re.sub(r'\s+', ' ', m.group(4) or ''))})
    last = int(pops[-1])
    head = next((c for c in cands if c['value'] == last), (cands[0] if cands else {}))
    if cands and head.get('value') != last:
        print('note: no headline matches the last scan (%s); published sentences: %s' %
              ('{:,}'.format(last), [c['value'] for c in cands]))
    extent = None
    m = re.search(r'for the whole Earth at\s*([\d,\u2019\.\s]+?)\s*million', html, re.I | re.S)
    if m:
        extent = int(re.sub(r'\D', '', m.group(1))) * 1_000_000
    return {'epochs': epochs, 'populations': pops, 'headline': head, 'naturalExtent': extent}


def world_bank(indicator):
    data = json.loads(get(WB_API % indicator, timeout=40))
    rows = [x for x in (data[1] or []) if x.get('value') is not None and x.get('date')]
    rows.sort(key=lambda x: -int(x['date']))
    return rows[0] if rows else None


def main():
    try:
        figu = parse_figu(get(FIGU_URL))
    except Exception as e:
        print('FIGU page unreadable (%s) — leaving worldpop.js untouched' % e)
        return 1

    cross = None
    try:
        tot = world_bank('SP.POP.TOTL')
        if tot:
            cross = {'source': 'World Bank SP.POP.TOTL (WLD)', 'year': int(tot['date']),
                     'value': int(tot['value'])}
    except Exception as e:
        print('World Bank cross-check unavailable (%s) — continuing without it' % e)

    head = figu['headline']
    series = [[e, p] for e, p in zip(figu['epochs'], figu['populations'])]
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    if head and head.get('value') != series[-1][1]:
        print('WARNING: headline %s != last scan %s — keeping both verbatim' %
              (head.get('value'), series[-1][1]))

    data = {
        '_updated': stamp,
        'source': 'FIGU · ca.figu.org',
        'url': FIGU_URL,
        'method': 'lagrange-quadratic-last-three-scans',
        'headline': head,
        'series': series,
        'naturalExtent': figu['naturalExtent'],
        'naturalExtentNote': 'Goblet of the Truth, quoted on the page: the extent appropriate for '
                             'the planet and nature for the whole Earth is 529 million human beings.',
        'crossCheck': cross,
    }
    content = ('// AUTO-GENERATED by fetch_worldpop.py — do not edit by hand.\n'
               '// FIGU population scans (ca.figu.org/overpopulation.html) + a labelled World Bank\n'
               '// cross-check. The dashboard ticks the FIGU series exactly as the FIGU page does:\n'
               '// a Lagrange quadratic through the last three published scans.\n'
               'window.WORLDPOP = ' + json.dumps(data, ensure_ascii=False) + ';\n')

    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        except Exception:
            prev = {}
    if prev.get('series') == series and (prev.get('headline') or {}).get('value') == (head or {}).get('value'):
        print('worldpop.js unchanged (last scan %s from %s) — %s' %
              ('{:,}'.format(series[-1][1]), datetime.datetime.fromtimestamp(
                  series[-1][0], datetime.timezone.utc).strftime('%Y-%m-%d'), stamp))
        return 0

    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote worldpop.js: %d scans, %s..%s, last %s%s' % (
        len(series),
        datetime.datetime.fromtimestamp(series[0][0], datetime.timezone.utc).strftime('%Y-%m-%d'),
        datetime.datetime.fromtimestamp(series[-1][0], datetime.timezone.utc).strftime('%Y-%m-%d'),
        '{:,}'.format(series[-1][1]),
        (' (headline increase %s)' % '{:,}'.format(head['increase'])) if head else ''))
    if cross:
        print('cross-check: World Bank %s = %s' % (cross['year'], '{:,}'.format(cross['value'])))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'worldpop.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'worldpop: FIGU scan snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
