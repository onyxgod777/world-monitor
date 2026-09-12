#!/usr/bin/env python3
"""render_daily_events.py — compose the World Monitor 'Daily Events' infographic
from daily/events_data.json, fully deterministically with PIL (no browser).

Real data only: live RSS headlines, the committed NCMEC amber snapshot, and the
committed market snapshot. The world map is stitched from the same CARTO dark
tiles the live site uses. Styling mirrors the site's dark palette.
"""
import json, os, math, glob, io, urllib.request, datetime, email.utils, textwrap
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, 'events_data.json'), encoding='utf-8'))
CACHE = os.path.join(HERE, '.tiles')
OUT = os.path.join(HERE, 'world-monitor-daily-events.png')

# ── palette (matches the live site) ──
BG=(5,8,15); PANEL=(15,23,41); PANEL2=(19,29,51); LINE=(30,42,65); LINE2=(43,58,88)
TEXT=(230,236,245); DIM=(167,182,205); MUTED=(107,122,148); FAINT=(65,80,108)
ACCENT=(110,168,254); AMBER=(245,158,11); GREEN=(34,197,94); RED=(239,68,68)

W, H = 1600, 1740
M = 24
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}

def font(sz, bold=False):
    cands = (glob.glob('/usr/share/fonts/**/Inter*Bold*.ttf', recursive=True) if bold
             else glob.glob('/usr/share/fonts/**/Inter*Regular*.ttf', recursive=True))
    if not cands:
        cands = ['/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf' % ('-Bold' if bold else '')]
    return ImageFont.truetype(cands[0], sz)

F = {k: font(*v) for k, v in {
    'brand':(30,True),'sub':(15,True),'date':(23,True),'gen':(13,False),
    'ctitle':(15,True),'cnt':(12,False),'sig':(15,False),'sign':(15,True),
    'hl':(15,False),'hlm':(12,False),'tag':(11,True),
    'msym':(13,True),'mpx':(23,True),'mchg':(14,True),'mlist':(13,False),
    'am':(15,True),'amm':(12,False),'note':(11,False),'foot':(13,False),
}.items()}

# ══════════ map: stitch CARTO dark tiles (web-mercator) ══════════
def latlon_px(lat, lng, size):
    x = (lng + 180.0) / 360.0 * size
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * size
    return x, y

def tile(z, x, y):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'{z}_{x}_{y}.png')
    if os.path.exists(p):
        return Image.open(p).convert('RGB')
    url = f'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            b = r.read()
        im = Image.open(io.BytesIO(b)).convert('RGB'); im.save(p); return im
    except Exception:
        return Image.new('RGB', (256, 256), PANEL)

Z = 3; N = 2 ** Z; TILE = 256; SIZE = N * TILE      # 2048 x 2048
def build_world():
    world = Image.new('RGB', (SIZE, SIZE), PANEL)
    for tx in range(N):
        for ty in range(N):
            world.paste(tile(Z, tx, ty), (tx*TILE, ty*TILE))
    return world

world = build_world()
# crop to populated latitudes (well inside the mercator poles)
y_top = int(latlon_px(80, 0, SIZE)[1])
y_bot = int(latlon_px(-58, 0, SIZE)[1])
world = world.crop((0, y_top, SIZE, y_bot))
CROP_W, CROP_H = world.size

MAP_W = W - 2*M - 2                  # card inner width
SC = MAP_W / CROP_W                  # uniform scale
MAP_H = int(CROP_H * SC)
world = world.resize((MAP_W, MAP_H), Image.LANCZOS)

img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)

def text(xy, s, fkey, fill=TEXT, anchor='la'):
    d.text(xy, str(s), font=F[fkey], fill=fill, anchor=anchor)

def wrap(s, fkey, maxw):
    words = str(s).split(); lines=[]; cur=''
    for wd in words:
        t = (cur+' '+wd).strip()
        if d.textlength(t, font=F[fkey]) <= maxw: cur=t
        else: lines.append(cur); cur=wd
    if cur: lines.append(cur)
    return lines

def card(x, y, w, h, r=12):
    d.rounded_rectangle([x, y, x+w, y+h], radius=r, fill=PANEL, outline=LINE, width=1)

def ellip(s, fkey, maxw):
    s = str(s)
    if d.textlength(s, font=F[fkey]) <= maxw:
        return s
    while s and d.textlength(s + '…', font=F[fkey]) > maxw:
        s = s[:-1]
    return s.rstrip() + '…'

def chead(x, y, w, title, right='', glyph=None):
    d.line([x, y+40, x+w, y+40], fill=LINE, width=1)
    tx = x + 14
    if glyph:
        d.text((tx, y+20), glyph, font=F['ctitle'], fill=AMBER, anchor='lm'); tx += 20
    d.text((tx, y+20), title, font=F['ctitle'], fill=DIM, anchor='lm')
    if right:
        d.text((x+w-14, y+20), right, font=F['cnt'], fill=MUTED, anchor='rm')

# ══════════ header ══════════
hy = 30
cx, cy, cr = 34, hy+16, 16
d.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], outline=ACCENT, width=2)
d.ellipse([cx-cr*0.5, cy-cr, cx+cr*0.5, cy+cr], outline=ACCENT, width=1)
d.line([cx-cr, cy, cx+cr, cy], fill=ACCENT, width=1)
d.line([cx, cy-cr, cx, cy+cr], fill=ACCENT, width=1)
text((cx+cr+14, hy+4), 'WORLD MONITOR', 'brand')
text((cx+cr+14, hy+40), 'D A I L Y   E V E N T S', 'sub', ACCENT)
text((W-M, hy+6), DATA['datestr'], 'date', TEXT, 'ra')
# live dot + generated
gx = W-M
text((gx, hy+42), 'generated '+DATA['generated'], 'gen', MUTED, 'ra')
gw = d.textlength('generated '+DATA['generated'], font=F['gen'])
d.ellipse([gx-gw-46-4, hy+46, gx-gw-46+4+4, hy+54], fill=GREEN)
text((gx-gw-46-12, hy+42), 'LIVE', 'gen', GREEN, 'ra')
d.line([M, hy+70, W-M, hy+70], fill=LINE, width=1)

# ══════════ map card ══════════
my = hy + 84
mcard_h = 40 + MAP_H + 36
card(M, my, W-2*M, mcard_h)
sig = DATA['signals']
amber = DATA.get('amber') or {}
acases = amber.get('cases') or []
chead(M, my, W-2*M, 'GLOBAL SITUATIONAL MAP',
      f"{len(sig)} regions with live signal · {len(acases)} NCMEC missing-child alerts")
img.paste(world, (M+1, my+41))
# overlay markers (project -> scale -> offset)
def to_img(lat, lng):
    px, py = latlon_px(lat, lng, SIZE)
    return M + px*SC, my + 41 + (py - y_top)*SC
for s in sig:
    x, y = to_img(s['lat'], s['lng'])
    r = (6 + min(s['hits'], 7) * 2.3) * SC * 1.05
    col = GREEN if s['hits'] <= 2 else (AMBER if s['hits'] <= 4 else RED)
    d.ellipse([x-r, y-r, x+r, y+r], fill=col, outline=(255,255,255), width=1)
for c in acases:
    if c.get('lat'):
        x, y = to_img(c['lat'], c['lng'])
        r = 9
        d.polygon([(x, y-r), (x+r, y), (x, y+r), (x-r, y)], fill=AMBER, outline=(255,255,255))
# legend
ly = my + 41 + MAP_H + 18
lx = M + 14
for lab, col, shape in [('active', GREEN, 'c'), ('heightened', AMBER, 'c'),
                        ('elevated', RED, 'c'), ('NCMEC missing-child alert', AMBER, 'd')]:
    if shape == 'c':
        d.ellipse([lx, ly-5, lx+10, ly+5], fill=col)
    else:
        d.polygon([(lx+5, ly-6), (lx+11, ly), (lx+5, ly+6), (lx-1, ly)], fill=col)
    d.text((lx+17, ly), lab, font=F['foot'], fill=MUTED, anchor='lm')
    lx += 17 + int(d.textlength(lab, font=F['foot'])) + 26

# ══════════ row 2 ══════════
ry = my + mcard_h + 14
RH = H - ry - 58
c1w, c2w, c3w = 470, 620, 434
c1x = M; c2x = c1x + c1w + 14; c3x = c2x + c2w + 14

# ── col1: signal heat ──
SH = 302
card(c1x, ry, c1w, SH)
chead(c1x, ry, c1w, 'SIGNAL HEAT · BY REGION', f"{DATA.get('total', len(DATA['news']))} headlines")
maxh = max([s['hits'] for s in sig], default=1)
yy = ry + 58
for s in sig[:8]:
    col = GREEN if s['hits'] <= 2 else (AMBER if s['hits'] <= 4 else RED)
    text((c1x+14, yy), s['name'][:19], 'sig', TEXT, 'lm')
    text((c1x+c1w-16, yy), s['hits'], 'sign', DIM, 'rm')
    bx = c1x+150; bw = c1w-150-52
    d.rounded_rectangle([bx, yy-4, bx+bw, yy+4], radius=4, fill=(10,17,32), outline=LINE, width=1)
    fillw = max(6, int(bw * s['hits']/maxh))
    d.rounded_rectangle([bx, yy-4, bx+fillw, yy+4], radius=4, fill=col)
    yy += 30

# ── col1b: amber ──
ay = ry + SH + 14; ah = RH - SH - 14
card(c1x, ay, c1w, ah)
chead(c1x, ay, c1w, 'AMBER · MISSING-CHILD', f"{len(acases)} active", glyph='◉')
yy = ay + 60
for c in acases[:4]:
    d.polygon([(c1x+16, yy-6), (c1x+22, yy), (c1x+16, yy+6), (c1x+10, yy)], fill=AMBER)
    nm = c['name'] + (f" · age {c['age']}" if c.get('age') is not None else '')
    text((c1x+32, yy), ellip(nm, 'am', c1w-46), 'am', TEXT, 'lm')
    text((c1x+32, yy+18), ellip((c.get('loc') or '') + (f" · since {c.get('missing')}" if c.get('missing') else ''), 'amm', c1w-46), 'amm', MUTED, 'lm')
    yy += 44
text((c1x+14, ay+ah-16), 'Coverage: NCMEC registry (US-anchored). Not a global AMBER feed.', 'note', FAINT, 'lm')

# ── col2: headlines ──
card(c2x, ry, c2w, RH)
by_region = {}
for n in DATA['news']:
    by_region.setdefault(n['region'], []).append(n)
headlines = []
for r in ['World', 'Geopolitics', 'Markets', 'Cyber', 'Energy', 'Climate']:
    headlines += by_region.get(r, [])[:2]
headlines = headlines[:11]
chead(c2x, ry, c2w, 'LIVE INTEL FEED · TOP EVENTS', 'public RSS')
TAGCOL = {'Geopolitics':((254,226,226),(153,27,27)),'Markets':((220,252,231),(22,101,52)),
          'Cyber':((254,243,199),(146,64,14)),'Energy':((237,233,254),(91,33,182)),
          'Climate':((209,250,229),(6,95,78)),'World':((219,234,254),(30,64,175))}
yy = ry + 62
for h in headlines:
    text((c2x+16, yy), ellip(h['title'], 'hl', c2w-32), 'hl', TEXT, 'lm')
    bg, fg = TAGCOL.get(h['region'], ((238,242,247),(51,65,85)))
    tw = int(d.textlength(h['region'], font=F['tag'])) + 14
    ty = yy + 17
    d.rounded_rectangle([c2x+16, ty, c2x+16+tw, ty+17], radius=5, fill=bg)
    text((c2x+16+tw/2, ty+8), h['region'], 'tag', fg, 'mm')
    agot = ''
    try:
        dt = email.utils.parsedate_to_datetime(h['pub'])
        mins = int((datetime.datetime.now(datetime.timezone.utc)-dt).total_seconds()//60)
        agot = 'now' if mins < 1 else (f'{mins}m' if mins < 60 else f'{mins//60}h')
    except Exception:
        pass
    text((c2x+16+tw+10, ty+8), f"{h['src']}  ·  {agot}", 'hlm', MUTED, 'lm')
    yy += 45
    d.line([c2x+16, yy-8, c2x+c2w-16, yy-8], fill=(24,34,53), width=1)

# ── col3: markets ──
card(c3x, ry, c3w, RH)
fiat = DATA.get('fiatleak') or {}
assets = fiat.get('assets') or {}
chead(c3x, ry, c3w, 'MARKETS', (fiat.get('_updated') or '')[:16])
marquee = [s for s in ['BTC','ETH','SOL','XRP','AAPL','NVDA'] if s in assets]
yy = ry + 54
for i, s in enumerate(marquee[:6]):
    px, ch = assets[s][0], assets[s][1]
    col = GREEN if ch >= 0 else RED
    colx = c3x + 14 + (i % 2)*(c3w//2)
    rowy = yy + (i//2)*66
    d.rounded_rectangle([colx, rowy, colx+(c3w//2)-10, rowy+58], radius=8, fill=PANEL2, outline=LINE)
    text((colx+12, rowy+10), s, 'msym', TEXT)
    text((colx+12, rowy+30), '$'+px, 'mpx', TEXT)
    text((colx+(c3w//2)-22, rowy+12), ('+' if ch>=0 else '')+str(ch)+'%', 'mchg', col, 'ra')
yy = ry + 54 + 3*66 + 10
gains = (fiat.get('topGainers') or [])[:5]
losses = (fiat.get('topLosers') or [])[:4]
text((c3x+16, yy), 'TOP GAINERS', 'ctitle', DIM); yy += 24
for s, v in gains:
    text((c3x+18, yy), s, 'mlist', TEXT, 'lm')
    text((c3x+c3w-18, yy), ('+' if v>=0 else '')+str(v)+'%', 'mlist', GREEN, 'rm'); yy += 22
yy += 8
text((c3x+16, yy), 'TOP LOSERS', 'ctitle', DIM); yy += 24
for s, v in losses:
    text((c3x+18, yy), s, 'mlist', TEXT, 'lm')
    text((c3x+c3w-18, yy), str(v)+'%', 'mlist', RED, 'rm'); yy += 22

# ══════════ footer ══════════
fy = H - 40
d.line([M, fy, W-M, fy], fill=LINE, width=1)
text((M, fy+20), 'Data: live public RSS · NCMEC missing-child registry · FiatLeak market snapshot', 'foot', MUTED, 'lm')
text((W//2, fy+20), f"{DATA.get('total', len(DATA['news']))} headlines · {len(sig)} regional signals · {len(acases)} alerts", 'foot', MUTED, 'mm')
text((W-M, fy+20), 'worldmonitor.thealpha-secret.xyz', 'foot', ACCENT, 'rm')

img.save(OUT)
print('wrote', OUT, img.size)
