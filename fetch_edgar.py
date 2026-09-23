#!/usr/bin/env python3
"""fetch_edgar.py — pull live SEC EDGAR filings into edgar.js.

EDGAR is the US regulator's own filing system: free, keyless, official, no account.
Three of its current-filings feeds are the useful ones for a monitoring dashboard:

    Form 4     insider transactions — officers, directors, 10% owners.
               The transaction CODE is the whole point: P = open-market purchase,
               S = sale. Without the code a Form 4 is noise (grants, tax
               withholding). The code is NOT in the feed, so the filing's own XML
               is read — index.json first to discover the filename, which is not
               predictable (e.g. wk-form4_1790122529.xml).
    13F-HR     quarterly institutional holdings reports — who is reporting.
    8-K        material corporate events.

All three are public documents; nothing here is licensed data and nothing needs a
key. SEC requires a descriptive User-Agent and asks for <=10 requests/second.

Usage:
    python3 fetch_edgar.py            # write edgar.js in place (if changed)
    python3 fetch_edgar.py --commit   # write + commit + push (only when changed)
"""
import datetime, json, os, re, subprocess, sys, urllib.request
import xml.etree.ElementTree as ET

HOME = os.path.expanduser('~')
REPO = os.environ.get('WM_REPO_DIR') or os.path.join(HOME, 'world-monitor')
OUT = os.path.join(REPO, 'edgar.js')

UA = {'User-Agent': 'WorldMonitor-EDGAR/1.0 (worldmonitor.thealpha-secret.xyz; '
                    'contact sunntzu@realvalueofpi.xyz)',
      'Accept': 'application/atom+xml, application/xml, text/xml, */*'}
# NOTE: do not ask for gzip — urllib does not decompress it, and the bytes then
# fail XML parsing with "not well-formed (invalid token)" at line 1, column 0.

CURRENT = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&company=&dateb='
           '&owner=include&count=%d&type=%s&output=atom')
FEEDS = [('4', 'insiders', 40), ('13F-HR', 'funds', 25), ('8-K', 'events', 25)]
MAX_ENRICH = 14          # how many Form 4 filings to open and read the code from

# Form 4 transaction codes that mean something on their own.
SIDE = {'P': 'buy', 'S': 'sell', 'A': 'grant', 'M': 'option', 'F': 'tax',
        'G': 'gift', 'C': 'conversion', 'D': 'disposition', 'J': 'other',
        'I': 'discretionary', 'W': 'will', 'E': 'expiry'}


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def localname(el):
    return el.tag.split('}')[-1]


def strip_ns(root):
    for el in root.iter():
        el.tag = localname(el)
    return root


def txt(node, path):
    if node is None:
        return ''
    found = node.find(path)
    if found is None or found.text is None:
        return ''
    return found.text.strip()


def parse_feed(xml_bytes, form_hint):
    """Atom entries -> list of dicts. Fields come from title + link + updated."""
    root = strip_ns(ET.fromstring(xml_bytes))
    out = []
    for e in root.findall('.//entry'):
        title = txt(e, 'title')
        if not title:
            continue
        # "4 - ChargePoint Holdings, Inc. (0001777393) (Issuer)"
        m = re.match(r'^([0-9A-Za-z/\-]+)\s+-\s+(.*?)\s+\((\d{10})\)\s*\((\w+)\)\s*$', title)
        if m:
            form, entity, cik, role = m.group(1), m.group(2), m.group(3), m.group(4)
        else:
            form, entity, cik, role = form_hint, title, '', ''
        link = ''
        for a in e.findall('link'):
            if a.get('href'):
                link = a.get('href')
                break
        out.append({
            'form': form, 'entity': entity, 'cik': cik, 'role': role,
            'filed': (txt(e, 'updated') or '')[:19], 'url': link,
        })
    return out


def enrich_form4(item, depth=0):
    """Open the filing, find its XML via index.json, read the real transaction."""
    m = re.search(r'/data/(\d+)/(\d+)/([0-9\-]+)-index\.htm', item.get('url', ''))
    if not m:
        return item
    cik, flat, accn = m.group(1), m.group(2), m.group(3)
    base = 'https://www.sec.gov/Archives/edgar/data/%s/%s/' % (cik, flat)
    try:
        idx = json.loads(get(base + 'index.json').decode('utf-8', 'ignore'))
        xmls = [i['name'] for i in idx.get('directory', {}).get('item', [])
                if i.get('name', '').lower().endswith('.xml')]
        if not xmls:
            return item
        root = strip_ns(ET.fromstring(get(base + xmls[0]).decode('utf-8', 'ignore')))
    except Exception as exc:
        if depth == 0:
            print('  form4 %s unreadable: %s' % (accn, exc))
        return item

    item['ticker'] = txt(root, './/issuerTradingSymbol')
    item['company'] = txt(root, './/issuerName') or item.get('entity', '')
    item['owner'] = txt(root, './/rptOwnerName') or item.get('entity', '')
    rel = root.find('.//reportingOwnerRelationship')
    if rel is not None:
        if txt(rel, 'isDirector') in ('1', 'true'):
            item['role'] = 'Director'
        elif txt(rel, 'isOfficer') in ('1', 'true'):
            item['role'] = txt(rel, 'officerTitle') or 'Officer'
        elif txt(rel, 'isTenPercentOwner') in ('1', 'true'):
            item['role'] = '10% owner'
    item['period'] = txt(root, 'periodOfReport')

    best = None
    for t in root.findall('.//nonDerivativeTransaction'):
        code = txt(t, './/transactionCode')
        shares = txt(t, './/transactionShares/value')
        price = txt(t, './/transactionPricePerShare/value')
        try:
            sh = float(shares) if shares else 0.0
            pr = float(price) if price else 0.0
        except ValueError:
            sh, pr = 0.0, 0.0
        cand = {
            'code': code, 'side': SIDE.get(code, 'other'),
            'shares': sh, 'price': pr, 'value': sh * pr,
            'date': txt(t, './/transactionDate/value') or item.get('period', ''),
            'ownedAfter': txt(t, './/sharesOwnedFollowingTransaction/value'),
            'security': txt(t, './/securityTitle/value'),
        }
        # prefer a real buy/sell over a housekeeping code, then the biggest trade
        rank = (1 if code in ('P', 'S') else 0, cand['value'])
        if best is None or rank > best[0]:
            best = (rank, cand)
    if best:
        item.update(best[1])
    return item


def main():
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    payload, ok, carried, failed_feeds = {}, 0, [], []

    # read the previous snapshot FIRST: if a feed is unreachable this run, its bucket is
    # carried forward rather than blanked. Publishing an empty list over good data is
    # worse than publishing yesterday's list, and SEC feeds do time out.
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.loads(open(OUT, encoding='utf-8').read().split('=', 1)[1].rsplit(';', 1)[0])
        except Exception:
            prev = {}

    for form, key, count in FEEDS:
        try:
            entries = parse_feed(get(CURRENT % (count, form)), form)
            ok += 1
        except Exception as exc:
            print('feed %s failed: %s' % (form, exc))
            failed_feeds.append(form)
            entries = []
        # an Atom entry is emitted once per party, so one Form 4 appears twice — once
        # under the issuer's CIK and once under the reporting owner's, same accession.
        # The accession is the HYPHENATED part of the filename (0001628280-26-063132),
        # not the 18-digit directory, so match the accession itself.
        # NB: do NOT name this `key` — that is the bucket name from the loop above.
        seen, uniq = set(), []
        for e in entries:
            m = re.search(r'/(\d{10}-\d{2}-\d{6})-index\.htm', e.get('url', ''))
            akey = m.group(1) if m else e.get('url', '')
            if akey in seen:
                continue
            seen.add(akey)
            uniq.append(e)
        entries = uniq
        # an empty/oversized entity name is a parse artefact, not a filing
        entries = [e for e in entries if e['entity'] and len(e['entity']) < 120]
        if key == 'insiders':
            entries = [enrich_form4(e) for e in entries[:MAX_ENRICH]]
            entries = [e for e in entries if e.get('code')]
            entries.sort(key=lambda e: (e.get('side') != 'buy', -(e.get('value') or 0)))
        # Carry forward rather than blank: a feed that returned nothing this cycle must
        # not wipe a good list. Only a non-empty result replaces a bucket.
        if not entries and prev.get(key):
            entries = prev[key]
            carried.append(key)
            print('  %s: feed returned nothing — kept %d entries from the previous snapshot'
                  % (key, len(entries)))
        payload[key] = entries

    if not any(payload.get(k) for _, k, _ in FEEDS):
        print('parsed 0 filings across all feeds — aborting to avoid clobbering')
        return 1

    ins = payload.get('insiders', [])
    data = {
        '_updated': stamp,
        'source': 'SEC EDGAR',
        'sources': '%d/%d feeds' % (ok, len(FEEDS)),
        'carried': carried,
        'failedFeeds': failed_feeds,
        'liability': 'Public filings, not investment advice.',
        'counts': {
            'insiders': len(ins),
            'buys': sum(1 for i in ins if i.get('side') == 'buy'),
            'sells': sum(1 for i in ins if i.get('side') == 'sell'),
            'funds': len(payload.get('funds', [])),
            'events': len(payload.get('events', [])),
        },
        'insiders': ins,
        'funds': payload.get('funds', []),
        'events': payload.get('events', []),
    }
    content = ('// AUTO-GENERATED by fetch_edgar.py — do not edit by hand.\n'
               '// Live SEC EDGAR current filings: Form 4 insider transactions (with the\n'
               '// transaction code read from each filing), 13F-HR holdings reports, 8-K events.\n'
               'window.EDGAR = ' + json.dumps(data, ensure_ascii=False) + ';\n')

    # change detection: a fresh timestamp alone must not spam git
    def sig(d):
        return json.dumps([[i.get('cik'), i.get('code'), round(i.get('shares') or 0)]
                           for i in d.get('insiders', [])]
                          + [[f.get('cik'), f.get('form')] for f in d.get('funds', [])]
                          + [[e.get('cik'), e.get('form')] for e in d.get('events', [])])

    if sig(data) == sig(prev):
        print('edgar.js unchanged (%d insider filings, %d funds, %d events)'
              % (len(ins), len(data['funds']), len(data['events'])))
        return 0

    open(OUT, 'w', encoding='utf-8').write(content)
    print('wrote edgar.js: %d insider filings (%d buys / %d sells), %d 13F, %d 8-K, %s'
          % (len(ins), data['counts']['buys'], data['counts']['sells'],
             len(data['funds']), len(data['events']), data['sources']))
    if '--commit' in sys.argv:
        subprocess.run(['git', '-C', REPO, 'add', 'edgar.js'], check=True)
        subprocess.run(['git', '-C', REPO, 'commit', '-m',
                        'edgar: SEC filings snapshot (%s)' % stamp[:16]], check=True)
        subprocess.run(['git', '-C', REPO, 'push', 'origin', 'main'], check=True)
        print('committed + pushed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
