#!/usr/bin/env python3
"""make_favicon.py — build the World Monitor favicon set from source.

The old favicon was the header logo shrunk down: a thin-stroked globe with two
hairline meridians plus an equator drawn at 1.1px. At a real 16px tab size those
hairlines collapse into grey mush and the mark is unreadable.

This builds a purpose-drawn mark instead, tuned for the tab strip:

  * dark rounded tile so it holds on light AND dark browser chrome
  * a thick accent ring (the world), drawn heavy enough to survive 16px
  * one meridian + equator at ~2.3/32 units — the minimum that still reads
  * an amber "live signal" dot at the centre with a tile-coloured halo, so it
    separates from the line crossing instead of smearing into it

Outputs (all written into the repo root):
  favicon.svg             — primary, scalable, rounded tile
  favicon.ico             — 16/32/48 multi-size, legacy + Windows taskbar
  favicon-16.png          — explicit tab size
  favicon-32.png
  favicon-48.png
  apple-touch-icon.png    — 180px, square (iOS applies its own corner mask),
                            mark inset to ~86% so nothing is clipped

Usage:
    python3 make_favicon.py            # build the set
    python3 make_favicon.py --check    # build nothing, report metrics of what's on disk
"""
import io, os, sys

REPO = os.path.dirname(os.path.abspath(__file__))

# Palette taken from styles.css so the icon matches the dashboard exactly.
TILE = '#0f1729'      # --panel
ACCENT = '#6ea8fe'    # --accent
LIVE = '#f59e0b'      # --amber
R = 10.4              # outer ring radius
SW = 3.0              # ring stroke
LINE = 2.3            # meridian / equator stroke
DOT, HALO = 4.4, 4.8  # live dot + its tile-coloured separation halo
                      # Tuned against real 16px renders: 3.6 left only 4 fully-lit
                      # pixels (a muddy speck), 4.4 lights 12-16 and — checked as
                      # connected components at 48px — the 4.8 halo no longer
                      # slices the meridian/equator (5.4+ fragmented them).


def svg(rounded=True, inset=0.0):
    """The mark. `inset` shrinks the globe about the tile centre (0..1)."""
    if inset:
        g0, g1 = ('<g transform="translate(16 16) scale(%g) translate(-16 -16)">' % (1 - inset)), '</g>'
    else:
        g0 = g1 = ''    # no wrapper needed for the default tile
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="World Monitor">
  <title>World Monitor</title>
  <rect width="32" height="32" rx="{7 if rounded else 0}" fill="{TILE}"/>
  {g0}
  <circle cx="16" cy="16" r="{R}" fill="none" stroke="{ACCENT}" stroke-width="{SW}"/>
  <ellipse cx="16" cy="16" rx="4.9" ry="{R}" fill="none" stroke="{ACCENT}" stroke-width="{LINE}" opacity=".95"/>
  <path d="M{16 - R + SW / 2:.2f} 16h{(R - SW / 2) * 2:.2f}" stroke="{ACCENT}" stroke-width="{LINE}"
        stroke-linecap="round" opacity=".95"/>
  <!-- live pulse: halo first so the bright dot never merges with the line crossing -->
  <circle cx="16" cy="16" r="{HALO}" fill="{TILE}"/>
  <circle cx="16" cy="16" r="{DOT}" fill="{LIVE}"/>
  {g1}
</svg>
'''


def cairosvg_bytes(markup, size):
    import cairosvg
    return cairosvg.svg2png(bytestring=markup.encode(), output_width=size, output_height=size)


def metrics(png_bytes, label):
    """Objective legibility check — we cannot eyeball a 16px icon, so measure it."""
    from PIL import Image
    im = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    w, h = im.size
    px = im.load()
    n = w * h

    def near(p, hexref, tol=26):
        r, g, b = p[0], p[1], p[2]
        rr = int(hexref[1:3], 16); gg = int(hexref[3:5], 16); bb = int(hexref[5:7], 16)
        return abs(r - rr) <= tol and abs(g - gg) <= tol and abs(b - bb) <= tol

    ink = amber = accent = 0
    for y in range(h):
        for x in range(w):
            p = px[x, y]
            if not near(p, TILE, 14):
                ink += 1
            if p[0] > 170 and 90 < p[1] < 210 and p[2] < 120:
                amber += 1
            if p[2] > 150 and p[2] > p[0] + 30 and p[1] > 90:
                accent += 1
    # tab-strip contrast: amber vs the accent lines it sits between
    con = abs(int(LIVE[1:3], 16) - int(ACCENT[1:3], 16)) + abs(int(LIVE[5:7], 16) - int(ACCENT[5:7], 16))
    print('%-22s %4dpx  ink=%5.1f%%  accent=%3dpx  amber=%3dpx  amber/accent=%+.0f' %
          (label, w, 100.0 * ink / n, accent, amber, con))
    return {'ink': 100.0 * ink / n, 'amber': amber, 'accent': accent, 'size': w}


def write_ico(path, frames):
    """Write a real multi-size .ico from per-size PNG payloads.

    PIL's ICO writer re-samples one bitmap for every size (and with
    append_images it silently emitted a 16px-only file). Each size here is
    rendered from the vector source instead, so every frame is crisp, and the
    directory is written explicitly so the sizes are guaranteed to be present.
    """
    import struct
    n = len(frames)
    header = struct.pack('<HHH', 0, 1, n)
    offset = 6 + 16 * n
    directory, blobs = b'', b''
    for size, data in frames:
        w = 0 if size >= 256 else size
        directory += struct.pack('<BBBBHHII', w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    with open(path, 'wb') as f:
        f.write(header + directory + blobs)


def main():
    os.chdir(REPO)
    if '--check' in sys.argv:
        for f in ('favicon-16.png', 'favicon-32.png', 'favicon-48.png', 'apple-touch-icon.png'):
            p = os.path.join(REPO, f)
            if os.path.exists(p):
                with open(p, 'rb') as fh:
                    metrics(fh.read(), f)
        print('meta on disk: %d bytes favicon.svg' % os.path.getsize(os.path.join(REPO, 'favicon.svg')))
        return 0

    mark = svg(rounded=True)
    apple = svg(rounded=False, inset=0.14)

    with open('favicon.svg', 'w', encoding='utf-8') as f:
        f.write(mark)

    sizes = {}
    for s in (16, 32, 48):
        data = cairosvg_bytes(mark, s)
        sizes[s] = data
        with open('favicon-%d.png' % s, 'wb') as f:
            f.write(data)
    with open('apple-touch-icon.png', 'wb') as f:
        f.write(cairosvg_bytes(apple, 180))

    write_ico('favicon.ico', [(s, sizes[s]) for s in (16, 32, 48)])

    print('wrote favicon.svg, favicon-{16,32,48}.png, apple-touch-icon.png, favicon.ico')
    for s in (16, 32, 48):
        metrics(sizes[s], 'favicon-%d.png' % s)
    return 0


if __name__ == '__main__':
    sys.exit(main())
