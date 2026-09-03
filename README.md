# World Monitor

A self-hosted global intelligence dashboard — live markets, geopolitical headlines, world clocks and risk signals in one dark, widescreen workspace. A clean static-shell homage to apps like world-monitor.app, built to run entirely on GitHub Pages.

Live: **https://onyxgod777.github.io/world-monitor/**

## Views
- **Markets** — live watchlist (BTC/ETH/SOL/XRP…) with prices, ±24h and 7d sparklines, an economic snapshot and a volatility/risk gauge. Data: [CoinGecko](https://www.coingecko.com) (free public API).
- **World** — 16 real-time city clocks + UTC.
- **Intel** — live headlines streamed from public RSS (world, markets, cyber, geopolitics, energy), tagged and auto-aged.
- **Alerts** — headlines auto-classified HIGH / MED / LOW priority.
- **World (board)** — status board, cyber-health grid and regional pulse derived from the live feed.

## Data honesty
- Crypto prices & clocks are **real-time**.
- The intel feed streams live Google News headlines via the rss2json API (CORS-enabled, no key), falling back to a public CORS proxy, then to clearly-labelled sample items if every source is unreachable. It recovers automatically on the next refresh.
- AI brief and risk gauge are labelled illustrative heuristics.

## Local run
```
python3 -m http.server 8000
# open http://localhost:8000
```

## Stack
Static: `index.html`, `styles.css`, `app.js` (no build step, no frameworks).
