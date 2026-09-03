# World Monitor

A self-hosted global intelligence dashboard — live markets, geopolitical headlines, world clocks and risk signals in one dark, widescreen workspace. A clean static-shell homage to apps like world-monitor.app, built to run entirely on GitHub Pages.

Live: **https://onyxgod777.github.io/world-monitor/**

## Views
- **Markets** — live crypto watchlist (BTC/ETH/SOL/XRP…) with prices, ±24h and sparklines ([CoinGecko](https://www.coingecko.com)); **Prediction Signals** from live Polymarket markets (Yes/No probabilities, 24h volume); **FX & Metals** (ECB/Frankfurter forex + real-time gold); an economic snapshot and volatility/risk gauge.
- **World** — 16 real-time city clocks + UTC.
- **Intel** — live headlines streamed from public RSS (world, markets, cyber, geopolitics, energy), tagged and auto-aged.
- **Alerts** — headlines auto-classified HIGH / MED / LOW priority.
- **World (board)** — a live world signal map (Leaflet/CARTO) plus status board, cyber grid and regional pulse derived from the live feed.

## Data honesty
- Crypto prices, forex, gold, prediction markets & clocks are **real-time** (all keyless, CORS-enabled public APIs).
- The intel feed streams live Google News headlines via rss2json (CORS, no key), falling back to a public CORS proxy, then to clearly-labelled sample items if every source is unreachable. It recovers automatically on refresh.
- Risk gauge and AI brief are labelled illustrative heuristics.
- Prediction-market probabilities are opinion data from Polymarket traders — not forecasts. Verify critical intelligence independently.

## Local run
```
python3 -m http.server 8000
# open http://localhost:8000
```

## Stack
Static: `index.html`, `styles.css`, `app.js` (no build step, no frameworks).
