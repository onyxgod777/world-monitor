#!/usr/bin/env python3
"""theme_audit.py — objective check on the HUD skin.

Renders the real index.html + styles.css in headless chromium with an injected
audit script, then reports:

  * WCAG contrast of every significant text style against its *composited*
    background (alpha-blended through all ancestors — the glass panels make the
    naive "text vs --panel" comparison wrong)
  * layout integrity: page overflow, card/pseudo-element presence
  * whether the intended webfonts actually applied

Usage: python3 theme_audit.py [--keep]
"""
import html, os, re, subprocess, sys, tempfile

REPO = '/home/kali/world-monitor'
AUDIT = r"""
<script>
window.addEventListener('load', () => setTimeout(() => {
  const parse = c => { const m = (c||'').match(/rgba?\(([^)]+)\)/); if(!m) return null;
    const p = m[1].split(',').map(Number);
    return {r:p[0], g:p[1], b:p[2], a: p.length>3 ? p[3] : 1}; };
  const bgOf = el => {
    const stack = []; for(let n = el; n; n = n.parentElement) stack.push(n);
    stack.reverse();
    let acc = {r:3, g:6, b:13};
    for(const n of stack){
      const c = parse(getComputedStyle(n).backgroundColor);
      if(c && c.a > 0.001) acc = { r:c.r*c.a + acc.r*(1-c.a), g:c.g*c.a + acc.g*(1-c.a), b:c.b*c.a + acc.b*(1-c.a) };
    }
    return acc;
  };
  const lum = c => { const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b); };
  const ratio = (a,b) => { const l1=lum(a), l2=lum(b), hi=Math.max(l1,l2), lo=Math.min(l1,l2);
    return (hi+0.05)/(lo+0.05); };

  const SEL = ['.card-head h2','.card-head .src','.count','.fitem .ftitle','.fitem .when','.fitem .fmeta',
    '.tag.region','.tag.src','.tag.unverified','.tile .sym','.tile .px','.tile .nm',
    '.clock .city','.clock .ct','.clock .cd','.clock .utc-tag','.dt thead th','.dt tbody td',
    '.srowline .k','.srowline .v','.cyb .cn','.cyb .cst','.cyb .cmeta','.region .rn','.region .rtemp',
    '.region .rl','.alert .atitle','.alert .asrc','.alert .at','.alert .sev','.prop .ptitle','.ptext',
    '.brief-body','.brief-note','.foot-note','.conn','.donateaddr .ad','.ticker-inner','.tk .up','.tk .dn',
    '.ph','.muted','.map-legend','.goldtile .gp','.goldtile .gn','.pq','.pmeta','.flmh','.flchip','.flprice',
    '.pill.up','.pill.watch','.badge.dang','.pcov','.ambernote','.ammeta','.amsrc','.utc','.beta','.live'];

  const rows = [], missing = [];
  for(const s of SEL){
    const el = document.querySelector(s);
    if(!el){ missing.push(s); continue; }
    const cs = getComputedStyle(el);
    const fg = parse(cs.color), bg = bgOf(el);
    if(!fg) continue;
    const blended = { r: fg.r*fg.a + bg.r*(1-fg.a), g: fg.g*fg.a + bg.g*(1-fg.a), b: fg.b*fg.a + bg.b*(1-fg.a) };
    const r = ratio(blended, bg);
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight)||400;
    const large = size >= 18.66 || (size >= 14 && weight >= 700);
    const need = large ? 3 : 4.5;
    rows.push([s, r.toFixed(2), (r >= need ? 'PASS' : (r >= need - 1.2 ? 'WARN' : 'FAIL')),
               cs.fontSize+'/'+cs.fontWeight, 'rgb('+Math.round(bg.r)+','+Math.round(bg.g)+','+Math.round(bg.b)+')'].join(' | '));
  }

  const de = document.documentElement;
  const facts = [
    'viewport | ' + window.innerWidth + 'x' + window.innerHeight,
    'h-overflow | ' + (de.scrollWidth > window.innerWidth + 2 ? 'YES ' + de.scrollWidth : 'no'),
    'cards | ' + document.querySelectorAll('.card').length,
    'card-brackets | ' + (getComputedStyle(document.querySelector('.card'),'::before').content !== 'none' ? 'yes' : 'NO'),
    'card-blur | ' + getComputedStyle(document.querySelector('.card')).backdropFilter,
    'card-bg | ' + getComputedStyle(document.querySelector('.card')).backgroundColor,
    'body-layers | ' + (getComputedStyle(document.body).backgroundImage.match(/gradient/g)||[]).length,
    'mono-font | ' + getComputedStyle(document.querySelector('.mono')).fontFamily.slice(0,42),
    'sans-font | ' + getComputedStyle(document.body).fontFamily.slice(0,42),
    'Inter-ready | ' + document.fonts.check('700 13px Inter'),
    'JetBrains-ready | ' + document.fonts.check('400 12px "JetBrains Mono"'),
    'tab-active-bar | ' + (getComputedStyle(document.querySelector('.tab.is-active'),'::after').opacity),
    'alert-rows | ' + document.querySelectorAll('#alertlist .alert').length,
    'feed-items | ' + document.querySelectorAll('#feed .fitem').length,
    'map-paths | ' + document.querySelectorAll('#worldmap .leaflet-overlay-pane path').length,
    'map-tiles | ' + document.querySelectorAll('#worldmap .leaflet-tile').length,
  ];
  const pre = document.createElement('pre'); pre.id = 'audit-report';
  pre.textContent = '@@AUDIT@@\n' + rows.join('\n') + '\n@@FACTS@@\n' + facts.join('\n')
                  + '\n@@MISSING@@\n' + (missing.join('\n') || 'none') + '\n@@END@@';
  document.body.appendChild(pre);
  document.title = 'AUDIT-READY';
}, 9000));
</script>
</body>"""


def main():
    keep = '--keep' in sys.argv
    src = open(os.path.join(REPO, 'index.html'), encoding='utf-8').read()
    if '</body>' not in src:
        sys.exit('index.html has no </body>')
    harness = os.path.join(REPO, '_audit.html')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(src.replace('</body>', AUDIT, 1))

    out = subprocess.run(
        ['/usr/bin/chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
         '--hide-scrollbars', '--window-size=1500,1000', '--virtual-time-budget=30000',
         '--dump-dom', 'file://' + harness],
        capture_output=True, text=True, timeout=180).stdout

    if not keep:
        os.remove(harness)

    # match the rendered <pre>, not the marker strings inside the injected script
    m = re.search(r'<pre id="audit-report">(.*?)</pre>', out, re.S)
    if not m:
        print('NO REPORT — page did not finish booting'); sys.exit(1)
    body = html.unescape(m.group(1))
    rows, facts, missing = [], [], []
    mode = None
    for line in body.strip().splitlines():
        if line.startswith('@@AUDIT@@'):
            mode = None; continue
        if line.startswith('@@FACTS@@'):
            mode = 'f'; continue
        if line.startswith('@@MISSING@@'):
            mode = 'm'; continue
        if line.startswith('@@END@@'):
            break
        if not line.strip():
            continue
        (rows if mode is None else facts if mode == 'f' else missing).append(line)

    print('=== CONTRAST (WCAG; WARN = within 1.2 of the floor) ===')
    fails = warns = 0
    for r in rows:
        sel, val, verdict = [x.strip() for x in r.split('|')[:3]]
        if verdict == 'FAIL':
            fails += 1
        elif verdict == 'WARN':
            warns += 1
        flag = {'PASS': '  ', 'WARN': ' !', 'FAIL': 'XX'}[verdict]
        print('%s %-22s %6s  %s' % (flag, sel, val, r.split('|', 3)[3].strip()))
    print('\n=== FACTS ===')
    for f in facts:
        print('   ' + f)
    print('\n=== SELECTORS NOT ON THIS VIEW ===')
    print('   ' + (', '.join(missing) if missing else 'none'))
    print('\nFAIL=%d  WARN=%d  of %d checked' % (fails, warns, len(rows)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
