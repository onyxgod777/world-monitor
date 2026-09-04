# World Monitor

A self-hosted global intelligence dashboard — live markets, geopolitical headlines, world clocks and risk signals in one dark, widescreen workspace. A clean static-shell homage to apps like world-monitor.app, built to run entirely on GitHub Pages.

Live: **https://onyxgod777.github.io/world-monitor/**

## Views
- **Markets** — live crypto watchlist (BTC/ETH/SOL/XRP…) with prices, ±24h and sparklines ([CoinGecko](https://www.coingecko.com)); **Prediction Signals** from live Polymarket markets (Yes/No probabilities, 24h volume); **FX & Metals** (ECB/Frankfurter forex + real-time gold); an economic snapshot and volatility/risk gauge.
- **World** — 16 real-time city clocks + UTC.
- **Intel** — live headlines streamed from public RSS (world, markets, cyber, geopolitics, energy), tagged and auto-aged.
- **Prophecy** — the daily *News & Prophecy* causal analyses from **pi.thealpha-secret.xyz/news/** rendered as tracked predictions: each tracks an **observed cause**, projects its **necessary effect if the cause persists**, and names **the hinge** — the human choice that changes the cause and rewrites the outcome. A live counter shows how many current feed headlines track each cause. Data lives in `prophecies.js` (update it when the news page publishes).
- **Alerts** — headlines auto-classified HIGH / MED / LOW priority.
- **World (board)** — a live world signal map (Leaflet/CARTO) plus status board, cyber grid and regional pulse derived from the live feed.

## Data honesty
- Crypto prices, forex, gold, prediction markets & clocks are **real-time** (all keyless, CORS-enabled public APIs).
- The intel feed streams live Google News headlines via a public CORS proxy (falling back to rss2json, then clearly-labelled sample items if every source is unreachable), auto-dropping known paywalled outlets so links open readable articles. It recovers automatically on refresh.
- Risk gauge and AI brief are labelled illustrative heuristics.
- The Prophecy tab's "headlines tracking" counter is a keyword heuristic over the live feed — an approximate gauge of coverage, not proof a prophecy is being fulfilled. Full analyses and their framing live on the source News & Prophecy page.
- Prediction-market probabilities are opinion data from Polymarket traders — not forecasts. Verify critical intelligence independently.

## Local run
```
python3 -m http.server 8000
# open http://localhost:8000
```

## Stack
Static: `index.html`, `styles.css`, `app.js` (no build step, no frameworks).
