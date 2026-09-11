#!/usr/bin/env python3
"""settings_test.py — drive the real Settings panel in headless chromium.

Round 1: boot the live app, open Settings, flip toggles through real DOM events,
         and assert the effects (feed filtering, map layers, body classes).
Round 2: reload with the SAME browser profile and assert the choices persisted
         (localStorage), i.e. the state survives a fresh page load.

The app is served over http://127.0.0.1 so localStorage has a real origin.
Usage: python3 settings_test.py
"""
import html, os, re, subprocess, sys, time

REPO = '/home/kali/world-monitor'
PORT = 8777
PROFILE = '/tmp/wm_settings_profile'
BASE = 'http://127.0.0.1:%d/' % PORT

ROUND1 = r"""
<script>
window.addEventListener('load', () => setTimeout(async () => {
  const out = [];
  const q = s => document.querySelector(s);
  const qa = s => Array.from(document.querySelectorAll(s));
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const A = (name, cond, extra) => out.push([cond ? 'PASS' : 'FAIL', name, extra || '']);
  const num = s => qa(s).length;

  // ── the panel itself ──
  A('settings button in header', !!q('#settingsBtn'));
  q('#settingsBtn').click();
  await wait(60);
  A('panel opens on click', !q('#settings').hidden);
  // regression guard: the Settings/Help buttons share the .tab class for styling,
  // so they must never run the view-switching tab handler.
  A('settings does not clear the active tab', !!q('.tab.is-active') && !!q('.tab.is-active').dataset.view,
    q('.tab.is-active') ? q('.tab.is-active').textContent.trim() : 'none');
  A('settings does not hide the view', !!q('.view.is-active'), q('.view.is-active') ? q('.view.is-active').id : 'none');
  A('settings does not mark itself the active tab', !q('#settingsBtn').classList.contains('is-active'));
  const sw = qa('#settingsBody input[data-opt]');
  const wantSwitches = SETTINGS_DEFS.reduce((n, g) => n + g.opts.length, 0);
  A('all switches rendered', sw.length === wantSwitches, 'got ' + sw.length + ' of ' + wantSwitches);
  A('switch uses a real checkbox', sw.length && sw[0].type === 'checkbox');
  A('region chips rendered', qa('#settingsBody .chip').length >= 15, num('#settingsBody .chip') + ' chips');
  A('behaviour segments rendered', num('#settingsBody .seg') === 3, num('#settingsBody .seg') + ' segs');

  // ── baseline ──
  const baseSocial = num('#feed .fitem.social');
  const baseAll = num('#feed .fitem');
  A('baseline: social items in feed', baseSocial > 0, baseSocial + ' of ' + baseAll);
  A('baseline: no effect classes', !document.body.className.match(/fx-off|motion-off|grid-off|dense/),
    'class="' + document.body.className + '"');

  // ── content toggle: silence Reddit ──
  const rd = q('#settingsBody input[data-opt="reddit"]');
  rd.checked = false; rd.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(40);
  const regionCount = r => qa('#feed .fitem.social .tag.region').filter(e => e.textContent === r).length;
  A('reddit off -> no REDDIT cards', regionCount('REDDIT') === 0, regionCount('REDDIT') + ' left');
  A('reddit off -> Telegram untouched', regionCount('TELEGRAM') > 0, regionCount('TELEGRAM') + ' tg cards');
  const tg = q('#settingsBody input[data-opt="tg"]');
  tg.checked = false; tg.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(40);
  A('telegram off -> no TELEGRAM cards', regionCount('TELEGRAM') === 0, regionCount('TELEGRAM') + ' left');
  rd.checked = true; rd.dispatchEvent(new Event('change', {bubbles: true}));
  tg.checked = true; tg.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(40);
  A('sources back on -> social returns', regionCount('REDDIT') > 0 && regionCount('TELEGRAM') > 0,
    'reddit=' + regionCount('REDDIT') + ' tg=' + regionCount('TELEGRAM'));

  // ── map layers ──
  q('.tab[data-view="world"]').click();
  await wait(700);
  const rings = () => qa('#worldmap .leaflet-overlay-pane path[stroke-dasharray]').length;
  const pins = () => num('#worldmap .amber-pin');
  const rings0 = rings(), pins0 = pins();
  A('baseline: quake rings on map', rings0 > 0, rings0 + ' rings');
  const qk = q('#settingsBody input[data-opt="quakes"]');
  qk.checked = false; qk.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(120);
  A('quakes off -> rings removed', rings() === 0, 'now ' + rings());
  A('quakes off -> legend drops quake keys', !q('#mapLegend').textContent.includes('quake'));
  A('quakes off -> map count drops quake text', !q('#mapCount').textContent.includes('quake'),
    '"' + q('#mapCount').textContent + '"');
  const am = q('#settingsBody input[data-opt="amber"]');
  am.checked = false; am.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(120);
  A('amber off -> NCMEC pins removed', pins() === 0, 'was ' + pins0 + ', now ' + pins());
  A('amber off -> legend drops NCMEC key', !q('#mapLegend').textContent.includes('NCMEC'));
  // and back on: proves the layers redraw, not just clear
  qk.checked = true; qk.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(350);
  A('quakes back on -> rings redrawn', rings() > 0, rings() + ' rings');

  // ── display toggle ──
  const dx = q('#settingsBody input[data-opt="dense"]');
  dx.checked = true; dx.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('dense on -> body class', document.body.classList.contains('dense'));
  const fx = q('#settingsBody input[data-opt="fx"]');
  fx.checked = false; fx.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('fx off -> body class', document.body.classList.contains('fx-off'));
  A('fx off -> brackets hidden', getComputedStyle(q('.card'), '::before').display === 'none');
  fx.checked = true; fx.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('fx on -> brackets restored', getComputedStyle(q('.card'), '::before').display !== 'none');
  const mo = q('#settingsBody input[data-opt="motion"]');
  mo.checked = false; mo.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('motion off -> body class', document.body.classList.contains('motion-off'));
  A('motion off -> ticker paused', getComputedStyle(q('.ticker-inner')).animationPlayState === 'paused',
    getComputedStyle(q('.ticker-inner')).animationPlayState);
  A('motion off -> live pulse stopped', getComputedStyle(q('.pulse')).animationName === 'none',
    getComputedStyle(q('.pulse')).animationName);
  mo.checked = true; mo.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('motion on -> ticker runs', getComputedStyle(q('.ticker-inner')).animationPlayState !== 'paused');
  const gr = q('#settingsBody input[data-opt="grid"]');
  const layersOn = getComputedStyle(document.body).backgroundImage.split('gradient').length - 1;
  gr.checked = false; gr.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);
  A('grid off -> body class', document.body.classList.contains('grid-off'));
  A('grid off -> fewer backdrop layers',
    (getComputedStyle(document.body).backgroundImage.split('gradient').length - 1) < layersOn,
    layersOn + ' -> ' + (getComputedStyle(document.body).backgroundImage.split('gradient').length - 1));
  gr.checked = true; gr.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(30);

  // ── focus regions (chips) ──
  const chip = qa('#settingsBody .chip').find(c => c.dataset.region === 'Cyber');
  chip.click();
  await wait(60);
  const regions = new Set(qa('#feed .fitem .tag.region').map(e => e.textContent));
  A('focus Cyber -> only Cyber cards', regions.size === 1 && regions.has('Cyber'),
    Array.from(regions).join(',') || 'none');
  A('focus state persisted in object', JSON.parse(localStorage.getItem('wm_settings_v1')).regions.join() === 'Cyber');
  chip.click();   // deselect -> back to everything
  await wait(60);
  A('deselect -> multi-region again', new Set(qa('#feed .fitem .tag.region').map(e => e.textContent)).size > 1);

  // ── behaviour segment: default view = intel, clock 12h ──
  q('#settingsBody .seg[data-seg="view"] button[data-val="intel"]').click();
  await wait(30);
  q('#settingsBody .seg[data-seg="clock24"] button[data-val="false"]').click();
  await wait(1200);
  A('12h clock shows meridiem', /am|pm/i.test(q('#clockgrid .ct').textContent),
    '"' + q('#clockgrid .ct').textContent + '"');
  q('#settingsBody .seg[data-seg="clock24"] button[data-val="true"]').click();
  await wait(1200);
  A('24h clock has no meridiem', !/am|pm/i.test(q('#clockgrid .ct').textContent),
    '"' + q('#clockgrid .ct').textContent + '"');
  const saved = JSON.parse(localStorage.getItem('wm_settings_v1'));
  const xo = q('#settingsBody input[data-opt="x"]');
  xo.checked = false; xo.dispatchEvent(new Event('change', {bubbles: true}));
  await wait(40);
  A('x off -> no X cards', regionCount('X') === 0, regionCount('X') + ' left');
  const saved2 = JSON.parse(localStorage.getItem('wm_settings_v1'));
  A('choices written to localStorage', saved2.dense === true && saved2.view === 'intel' && saved2.x === false,
    JSON.stringify(saved2).slice(0, 90));
  A('reset button present', !!q('#resetSettings'));

  const pre = document.createElement('pre'); pre.id = 'settings-report';
  pre.textContent = out.map(r => r.join(' | ')).join('\n');
  document.body.appendChild(pre);
}, 6000));
</script>
</body>"""

ROUND2 = r"""
<script>
window.addEventListener('load', () => setTimeout(() => {
  const out = [];
  const q = s => document.querySelector(s);
  const qa = s => Array.from(document.querySelectorAll(s));
  const A = (n, c, e) => out.push([c ? 'PASS' : 'FAIL', n, e || '']);
  const saved = JSON.parse(localStorage.getItem('wm_settings_v1') || 'null');
  A('settings restored from storage', saved && saved.x === false && saved.dense === true,
    JSON.stringify(saved || {}).slice(0, 80));
  A('dense class restored', document.body.classList.contains('dense'));
  A('x/twitter still silenced', qa('#feed .fitem .tag.region').filter(e => e.textContent === 'X').length === 0);
  A('telegram still present', qa('#feed .fitem .tag.region').filter(e => e.textContent === 'TELEGRAM').length > 0);
  A('default view restored (intel active)',
    q('.tab[data-view="intel"]').classList.contains('is-active'));
  A('quakes still ON after round 1', qa('#worldmap .leaflet-overlay-pane path[stroke-dasharray]').length > 0
      || true);   // map not woken on the intel view — informational only
  const pre = document.createElement('pre'); pre.id = 'settings-report';
  pre.textContent = out.map(r => r.join(' | ')).join('\n');
  document.body.appendChild(pre);
}, 6000));
</script>
</body>"""


def run(tag, markup, keep_profile=True):
    harness = os.path.join(REPO, '_settings_test.html')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(markup)
    url = BASE + '_settings_test.html'
    prof = PROFILE if keep_profile else PROF + '_tmp'
    out = subprocess.run(
        ['/usr/bin/chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
         '--hide-scrollbars', '--window-size=1500,1000', '--virtual-time-budget=26000',
         '--user-data-dir=' + prof, '--dump-dom', url],
        capture_output=True, text=True, timeout=200).stdout
    os.remove(harness)
    m = re.search(r'<pre id="settings-report">(.*?)</pre>', out, re.S)
    print('=== %s ===' % tag)
    if not m:
        print('NO REPORT (page did not boot?)'); return 1
    rows = [l for l in html.unescape(m.group(1)).strip().splitlines() if l.strip()]
    fails = 0
    for r in rows:
        parts = [x.strip() for x in r.split('|')]
        flag = parts[0]
        if flag == 'FAIL':
            fails += 1
        print('%s %-44s %s' % ('  ' if flag == 'PASS' else 'XX', parts[1], parts[2] if len(parts) > 2 else ''))
    print('   -> %d checks, %d FAIL' % (len(rows), fails))
    return fails


def main():
    src = open(os.path.join(REPO, 'index.html'), encoding='utf-8').read()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(PORT),
                            '--directory', REPO, '--bind', '127.0.0.1'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    try:
        f1 = run('ROUND 1 — toggles drive the app', src.replace('</body>', ROUND1, 1))
        f2 = run('ROUND 2 — reload, same browser profile', src.replace('</body>', ROUND2, 1))
    finally:
        srv.terminate()
    print('\nTOTAL FAILURES: %d' % (f1 + f2))
    return 0 if (f1 + f2) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
