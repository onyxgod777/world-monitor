/* ═══════════════════════════════════════════════════════════
   WORLD MONITOR — app.js
   Real live feeds where easy (crypto markets, world clocks, news
   RSS via CORS proxy). Heuristic/illustrative panels are labelled.
   Every fetch degrades gracefully to a fallback so the dashboard
   always renders. Refresh cycle: clocks 1s, crypto 60s, news 2m.
   ═══════════════════════════════════════════════════════════ */

'use strict';

const $ = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => Array.from(r.querySelectorAll(s));

/* ───────── helpers ───────── */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mono = (n, d=2) => Number(n).toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
const signed = n => (n>0?'+':'') + mono(n);
const clsDelta = n => n>0?'up':(n<0?'dn':'flat');
const pct = n => (n>0?'+':'') + mono(n,2) + '%';

// Robust feed-date parsing + age label. Feed dates come in two formats:
//  - RFC822 GMT from live RSS  ("Sat, 05 Sep 2026 21:16:33 GMT")
//  - naive "YYYY-MM-DD HH:MM:SS" from rss2json (which is GMT under the hood)
// Date.parse on the naive form is browser-dependent; normalize it to UTC. If a
// date cannot be parsed at all we return NaN — callers must NEVER treat that as
// "now": an undatable item is shown with no age and ranked as oldest, not fresh.
function parseTs(pub){
  if(!pub) return NaN;
  const p = String(pub).trim();
  let t = Date.parse(p);
  if(isNaN(t)){
    const m = p.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)/);
    if(m) t = Date.parse(m[1] + 'T' + m[2] + 'Z');   // treat naive feed time as UTC/GMT
  }
  return t; // may still be NaN -> caller ranks it oldest, no "now"
}
function agoLabel(ts, now){
  if(!(ts > 0)) return '';                 // unknown age -> show nothing, never 'now'
  const ago = Math.max(0, Math.round((now - ts) / 60000));
  return ago < 1 ? 'now' : (ago < 60 ? ago + 'm' : Math.round(ago / 60) + 'h');
}

const PROXIES = [
  'https://api.allorigins.win/raw?url=',
  'https://api.codetabs.com/v1/proxy?quest=',
  'https://api.corsproxy.io/?url=',
  'https://test.cors.workers.dev/?url=',
  'https://cors.eu.org/',
  'https://api.cors.lol/?url=',
];
// remember the first proxy that works this session
let _activeProxy = 0;
async function fetchTimeout(url, ms=5000){
  const ctl = new AbortController();
  const t = setTimeout(()=>ctl.abort(), ms);
  try{ return await fetch(url, {signal:ctl.signal}); }
  finally{ clearTimeout(t); }
}
async function proxied(url){
  const target = encodeURIComponent(url);
  // Fire all proxies in parallel and resolve on the FIRST success, so a slow or
  // dead proxy can't stall the dashboard and a working one answers immediately.
  return new Promise((resolve,reject)=>{
    let settled=0; let lastErr;
    for(let i=0;i<PROXIES.length;i++){
      (async (idx)=>{
        try{
          const res = await fetchTimeout(PROXIES[idx]+target, 4200);
          if(!res.ok) throw new Error('proxy '+idx+' '+res.status);
          _activeProxy=idx; resolve(res);
        }catch(e){
          lastErr=e;
          if(++settled===PROXIES.length) reject(lastErr||new Error('no proxy'));
        }
      })(i);
    }
  });
}

/* ───────── app state ───────── */
const S = { coins: [], news: [], online: false, lastFetch: 0 };

/* ══════════════ 0. SETTINGS (localStorage, client-side only) ══════════════ */
// Every option lives in the browser — no account, no backend, nothing to sync.
// Display options are applied as classes on <body>; content and map-layer options
// are read directly by the render functions, so flipping one never has to re-fetch
// anything. This block is deliberately first so SET exists before any render runs.
const SETTINGS_KEY = 'wm_settings_v1';
const SETTINGS_DEFS = [
  { group:'Display', opts:[
    { k:'fx',     lab:'HUD effects',     hint:'Corner brackets, glows and the header scan sweep' },
    { k:'motion', lab:'Motion',          hint:'Animated live pulse and scrolling market ticker' },
    { k:'grid',   lab:'Grid backdrop',   hint:'44px technical grid behind the panels' },
    { k:'dense',  lab:'Compact density', hint:'Tighter feed, alert and tile spacing' },
  ]},
  { group:'Intel sources', opts:[
    { k:'tg',     lab:'Telegram',    hint:'Public channel previews · unverified first reports' },
    { k:'reddit', lab:'Reddit',      hint:'Public subreddit feeds · unverified first reports' },
    { k:'x',      lab:'X / Twitter', hint:'Public timeline widget — cached per handle' },
  ]},
  { group:'Map layers', opts:[
    { k:'quakes', lab:'Seismic activity',   hint:'Live USGS — dashed magnitude rings, M2.5+' },
    { k:'floods', lab:'Flood alerts',       hint:'Live GDACS global events + NOAA/NWS US warnings' },
    { k:'outbreaks', lab:'Outbreak reports', hint:'Live WHO Disease Outbreak News bulletins' },
    { k:'amber',  lab:'Missing-child pins', hint:'NCMEC alert cases (US-anchored registry)' },
  ]},
];
const SETTINGS_SEGS = [
  { k:'view',    lab:'Default view',    hint:'Section shown when the page opens', vals:[
      ['markets','Markets'],['intel','Intel'],['prophecy','Prophecy'],['world','World'],['alerts','Alerts'] ] },
  { k:'clock24', lab:'Clock format',    hint:'World clocks and the UTC readout', vals:[
      [true,'24h'],[false,'12h'] ] },
  { k:'refresh', lab:'Intel refresh',   hint:'How often the feed re-reads the snapshot', vals:[
      [0,'Off'],[120000,'2 min'],[300000,'5 min'],[900000,'15 min'] ] },
  { k:'mapMode', lab:'World map view',  hint:'2D map or 3D rotating globe', vals:[
      ['2d','2D map'],['3d','3D globe'] ] },
];
const SETTINGS_DEFAULTS = { fx:true, motion:true, grid:true, dense:false,
  tg:true, reddit:true, x:true, quakes:true, floods:true, outbreaks:true, amber:true,
  regions:[], view:'markets', clock24:true, refresh:120000, mapMode:'2d' };
let SET = (function(){
  try{ return Object.assign({}, SETTINGS_DEFAULTS, JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}')); }
  catch(e){ return Object.assign({}, SETTINGS_DEFAULTS); }   // corrupt/blocked storage -> defaults
})();
function saveSettings(){ try{ localStorage.setItem(SETTINGS_KEY, JSON.stringify(SET)); }catch(e){} }
// a platform toggle silences that whole source (region tag doubles as the platform id)
function platformEnabled(region){
  if(region === 'TELEGRAM') return !!SET.tg;
  if(region === 'REDDIT')   return !!SET.reddit;
  if(region === 'X')        return !!SET.x;
  return true;
}
function regionOptions(){
  return [...new Set(NEWS_FEEDS.map(f=>f.region).concat(['TELEGRAM','REDDIT','X']))];
}
let _refreshTimer = null;
function restartRefresh(){
  if(_refreshTimer){ clearInterval(_refreshTimer); _refreshTimer = null; }
  if(SET.refresh > 0) _refreshTimer = setInterval(loadNews, SET.refresh);
}
function applySettings(){
  const b = document.body;
  b.classList.toggle('fx-off',     !SET.fx);
  b.classList.toggle('motion-off', !SET.motion);
  b.classList.toggle('grid-off',   !SET.grid);
  b.classList.toggle('dense',      !!SET.dense);
  try{ loadNews(); }catch(e){ /* panel not built yet */ }
  try{ if(_map) updateMapSignals(); }catch(e){}
  // reflect the saved world-map mode (initialise the globe only when it is on-screen)
  try{
    const is3 = SET.mapMode === '3d';
    const worldActive = $('#view-world') && $('#view-world').classList.contains('is-active');
    if(is3 && worldActive){
      setMapMode('3d');
    }else{
      const gb = $('#globebox'); if(gb) gb.hidden = !is3;
      const two = $('#worldmap'); if(two) two.style.display = is3 ? 'none' : '';
      const b2 = $('#map2dBtn'), b3 = $('#map3dBtn');
      if(b2){ b2.classList.toggle('is-on', !is3); b2.setAttribute('aria-pressed', String(!is3)); }
      if(b3){ b3.classList.toggle('is-on', is3);  b3.setAttribute('aria-pressed', String(is3)); }
      if(!is3) stopGlobe();
    }
  }catch(e){}
  try{ tickClocks(); }catch(e){}
  restartRefresh();
  const st = $('#settingsSaved');
  if(st) st.textContent = 'saved ' + new Date().toLocaleTimeString('en-GB');
}
function renderSettings(){
  const sw = o => `<label class="switch">
      <span class="setlab"><b>${esc(o.lab)}</b><i>${esc(o.hint)}</i></span>
      <input type="checkbox" data-opt="${o.k}" ${SET[o.k] ? 'checked' : ''}>
      <span class="track" aria-hidden="true"></span>
    </label>`;
  let html = SETTINGS_DEFS.map(g =>
    `<div class="setgrp"><h3>${esc(g.group)}</h3>${g.opts.map(sw).join('')}</div>`).join('');
  html += `<div class="setgrp"><h3>Focus regions</h3>
    <div class="chips">${regionOptions().map(r =>
      `<button class="chip${SET.regions.indexOf(r) >= 0 ? ' on' : ''}" data-region="${esc(r)}">${esc(r)}</button>`).join('')}</div>
    <div class="sethint">Nothing selected = every region. A selection filters the Intel feed and the map's news signals.</div></div>`;
  html += `<div class="setgrp"><h3>Behaviour</h3>` + SETTINGS_SEGS.map(s =>
    `<div class="setrow"><span class="setlab"><b>${esc(s.lab)}</b><i>${esc(s.hint)}</i></span>
      <span class="seg" data-seg="${s.k}">${s.vals.map(([v, l]) =>
        `<button data-val="${v}" class="${String(SET[s.k]) === String(v) ? 'on' : ''}">${esc(l)}</button>`).join('')}</span>
    </div>`).join('') + `</div>`;
  $('#settingsBody').innerHTML = html;
}
function bindSettings(){
  const modal = $('#settings'), panel = $('#settingsBody');
  const close = () => { modal.hidden = true; };
  const open  = () => { renderSettings(); modal.hidden = false; };
  $('#settingsBtn').addEventListener('click', open);
  $('#closeSettings').addEventListener('click', close);
  $('#doneSettings').addEventListener('click', close);
  modal.addEventListener('click', e => { if(e.target === modal) close(); });
  document.addEventListener('keydown', e => { if(e.key === 'Escape' && !modal.hidden) close(); });
  $('#resetSettings').addEventListener('click', () => {
    SET = Object.assign({}, SETTINGS_DEFAULTS);
    saveSettings(); renderSettings(); applySettings();
  });
  panel.addEventListener('change', e => {
    const k = e.target && e.target.dataset ? e.target.dataset.opt : null;
    if(!k) return;
    SET[k] = e.target.checked;
    saveSettings(); applySettings();
  });
  panel.addEventListener('click', e => {
    const chip = e.target.closest && e.target.closest('.chip');
    if(chip){
      const r = chip.dataset.region, i = SET.regions.indexOf(r);
      if(i >= 0) SET.regions.splice(i, 1); else SET.regions.push(r);
      chip.classList.toggle('on', SET.regions.indexOf(r) >= 0);
      saveSettings(); applySettings();
      return;
    }
    const segBtn = e.target.closest && e.target.closest('.seg button');
    if(segBtn){
      const seg = segBtn.closest('.seg'), k = seg.dataset.seg, raw = segBtn.dataset.val;
      const d = SETTINGS_DEFAULTS[k];
      SET[k] = (typeof d === 'boolean') ? (raw === 'true') : (typeof d === 'number' ? Number(raw) : raw);
      saveSettings();
      seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === segBtn));
      applySettings();
    }
  });
}

function setStatus(ok, label){
  const el = $('#connStatus');
  el.className = 'conn mono ' + (ok?'ok':'bad');
  el.innerHTML = `<span class="dot"></span>${label}`;
  S.online = ok;
}

/* ══════════════ 1. WORLD CLOCKS (real, client-side) ══════════════ */
const ZONES = [
  ['UTC','UTC'], ['New York','America/New_York'], ['Toronto','America/Toronto'],
  ['Los Angeles','America/Los_Angeles'], ['Sao Paulo','America/Sao_Paulo'],
  ['London','Europe/London'], ['Frankfurt','Europe/Berlin'], ['Moscow','Europe/Moscow'],
  ['Istanbul','Europe/Istanbul'], ['Dubai','Asia/Dubai'], ['New Delhi','Asia/Kolkata'],
  ['Singapore','Asia/Singapore'], ['Beijing','Asia/Shanghai'], ['Tokyo','Asia/Tokyo'],
  ['Sydney','Australia/Sydney'], ['Auckland','Pacific/Auckland'],
];
function zoneFmt(zone, now){
  const h12 = !SET.clock24;
  const opts = { timeZone: zone, hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:h12 };
  const time = new Intl.DateTimeFormat(h12 ? 'en-US' : 'en-GB', opts).format(now);
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: zone, weekday:'short' }).format(now);
  return { time, day };
}
function tickClocks(){
  const now = new Date();
  $('#utcClock').textContent = new Intl.DateTimeFormat(SET.clock24 ? 'en-GB' : 'en-US',
    {timeZone:'UTC',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:!SET.clock24}).format(now) + ' UTC';
  const g = $('#clockgrid');
  g.innerHTML = ZONES.map(([city,zone])=>{
    const {time,day} = zoneFmt(zone, now);
    const off = (zone==='UTC') ? '' : `<span class="utc-tag">${utcOffsetLabel(zone,now)}</span>`;
    return `<div class="clock"><div class="city">${city}</div><div class="ct">${time}</div><div class="cd">${day} ${off}</div></div>`;
  }).join('');
}
function utcOffsetLabel(zone, now){
  try{
    const dtf = new Intl.DateTimeFormat('en-US',{timeZone:zone,timeZoneName:'shortOffset'});
    const parts = dtf.formatToParts(now).find(p=>p.type==='timeZoneName');
    return (parts && parts.value) || '';
  }catch(e){ return ''; }
}

/* ══════════════ 2. CRYPTO MARKETS (real, CoinGecko) ══════════════ */
const COINS = ['bitcoin','ethereum','solana','binancecoin','ripple','cardano','dogecoin','avalanche-2','chainlink','polkadot','polygon-ecosystem-token','litecoin'];
const COIN_NAME = {bitcoin:'BTC',ethereum:'ETH',solana:'SOL',binancecoin:'BNB',ripple:'XRP',cardano:'ADA',dogecoin:'DOGE','avalanche-2':'AVAX',chainlink:'LINK',polkadot:'DOT','polygon-ecosystem-token':'POL',litecoin:'LTC'};
const COIN_BRAND = {bitcoin:'#F7931A',ethereum:'#627EEA',solana:'#14F195',binancecoin:'#F3BA2F',ripple:'#23A8DF',dogecoin:'#C2A633',chainlink:'#2A5ADA',litecoin:'#3D7BD6'};
const brandOf=id=>COIN_BRAND[id]||null;

// Persist the last good CoinGecko snapshot so a transient throttle / network blip
// falls back to real (recent) prices instead of a blank "unreachable" panel.
const _MKT_CACHE_KEY = 'wm_mkt_cache_v1';
function cacheGet(){
  try{ const raw = localStorage.getItem(_MKT_CACHE_KEY); return raw ? JSON.parse(raw) : null; }
  catch(e){ return null; }
}
function cacheSet(coins){
  try{
    localStorage.setItem(_MKT_CACHE_KEY, JSON.stringify(coins.map(c=>({
      id:c.id, name:c.name, symbol:c.symbol, image:c.image,
      current_price:c.current_price, price_change_percentage_24h:c.price_change_percentage_24h,
      price_change_percentage_7d:c.price_change_percentage_7d, market_cap:c.market_cap,
      market_cap_rank:c.market_cap_rank,
      sparkline_in_7d:c.sparkline_in_7d ? {price:c.sparkline_in_7d.price} : undefined
    }))));
  }catch(e){ /* localStorage full or blocked — non-fatal */ }
}
function markMkt(src){ $('#mktSrc').textContent = src; }

async function loadMarkets(){
  // 1) Full CoinGecko snapshot (direct, then via any working proxy). Best data.
  const cg = await tryCoinGecko();
  if(cg && cg.length){ commitCoins(cg, 'COINGECKO · LIVE', true); return; }
  // 2) Fresh 24h prices via Binance, merged over the last known snapshot so the
  //    panel keeps mcap/rank/sparkline. Best-effort: api.binance.com returns 451
  //    for some regions, in which case this fails cleanly and we move on.
  const bin = await tryBinance();
  if(bin && bin.length){ commitCoins(bin, 'BINANCE · LIVE', true); return; }
  // 3) CoinGecko throttled/down and no fresh overlay: keep the last good snapshot
  //    (stale but real). Recovers automatically on the next successful live tick.
  const cached = cacheGet();
  if(cached && cached.length){ commitCoins(cached, 'LAST KNOWN · STALE', false); return; }
  // 4) Nothing has ever loaded — genuine offline state (cold visit + every source down).
  renderMarketsOffline();
}

async function tryCoinGecko(){
  const ids = COINS.join(',');
  const url = `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids}&order=market_cap_desc&per_page=50&sparkline=true&price_change_percentage=24h%2C7d`;
  let res=null;
  try{ res = await fetchTimeout(url, 9000); if(!res.ok) res=null; }catch(e){ res=null; }
  if(!res){ try{ res = await proxied(url); }catch(e){ res=null; } }
  if(!res) return null;
  try{ const j = await res.json(); return Array.isArray(j) ? j.filter(c=>COIN_NAME[c.id]) : null; }
  catch(e){ return null; }
}

const _SYM2ID = Object.fromEntries(Object.entries(COIN_NAME).map(([id,sym])=>[sym,id]));
async function tryBinance(){
  const syms = COINS.map(id=>COIN_NAME[id]+'USDT').filter(Boolean);
  if(!syms.length) return null;
  try{
    const res = await fetchTimeout('https://api.binance.com/api/v3/ticker/24hr?symbols='+encodeURIComponent(JSON.stringify(syms)), 8000);
    if(!res.ok) return null;
    const arr = await res.json(); if(!Array.isArray(arr)) return null;
    const px = {};
    arr.forEach(t=>{ const id=_SYM2ID[(t.symbol||'').replace(/USDT$/,'')]; if(id) px[id]={ current_price:parseFloat(t.lastPrice), price_change_percentage_24h:parseFloat(t.priceChangePercent) }; });
    if(!Object.keys(px).length) return null;
    const base = (S.coins && S.coins.length) ? S.coins : COINS.map(id=>({id, name:COIN_NAME[id]}));
    return base.map(c=>Object.assign({}, c, px[c.id]||{}));
  }catch(e){ return null; }
}

function commitCoins(coins, label, persist){
  S.coins = coins;
  S.online = !label.includes('STALE');
  markMkt(label);
  if(persist) cacheSet(coins);
  renderMarkets();
  renderEcon();
  renderRisk();
}
function renderMarkets(){
  const coins = S.coins;
  // ticker
  const tk = coins.map(c=>{
    const cls = clsDelta(c.price_change_percentage_24h);
    const bc = brandOf(c.id);
    return `<span class="tk"><span class="c" style="color:${bc||'var(--text-dim)'}">${COIN_NAME[c.id]}</span> <b>$${mono(c.current_price)}</b> <span class="${cls}">${pct(c.price_change_percentage_24h)}</span></span><span class="sep"></span>`;
  }).join('');
  $('#ticker').innerHTML = `<span class="ticker-inner">${tk}${tk}</span>`;
  // watch tiles with sparkline
  const max = coins.reduce((m,c)=>Math.max(m,...(c.sparkline_in_7d?.price||[])),1);
  const min = coins.reduce((m,c)=>Math.min(m,...(c.sparkline_in_7d?.price||[])),0);
  $('#watchgrid').innerHTML = coins.map(c=>{
    const d1 = c.price_change_percentage_24h ?? 0;
    const bc = brandOf(c.id);
    const spark = sparkSVG(c.sparkline_in_7d?.price, min, max, d1>=0?'#22c55e':'#ef4444');
    return `<div class="tile">
      <div class="symrow"><span class="sym" style="color:${bc||'var(--text)'}">${COIN_NAME[c.id]}</span><span class="nm">${esc(c.name)} · #${c.market_cap_rank||''}</span></div>
      <div class="px">$${mono(c.current_price)}</div>
      <div class="chg"><span class="delta ${clsDelta(d1)}">${pct(d1)}</span>${spark}<span style="margin-left:auto;font-size:9px;color:var(--faint)">7D</span></div>
    </div>`;
  }).join('');
}
function sparkSVG(arr,min,max,col){
  if(!arr||!arr.length) return '';
  const W=72,H=18; const span=(max-min)||1;
  const pts=arr.map((v,i)=>`${(i/(arr.length-1)*W).toFixed(1)},${(H-2-((v-min)/span)*(H-4)).toFixed(1)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/></svg>`;
}
function renderMarketsOffline(){
  $('#mktSrc').textContent = 'OFFLINE · RETRYING';
  const tpl=['BTC','ETH','SOL','XRP'];
  $('#ticker').innerHTML = `<span class="ticker-inner">${tpl.map(s=>`<span class="tk">${s} <span class="flat">— offline —</span></span><span class="sep"></span>`).join('')}${tpl.map(s=>`<span class="tk">${s} <span class="flat">— offline —</span></span><span class="sep"></span>`).join('')}</span>`;
  $('#watchgrid').innerHTML = `<div class="ph mono" style="grid-column:1/-1;padding:20px;text-align:center">Live price feed unavailable right now — retrying automatically. If this persists on this network, the feed is rate-limiting your connection.</div>`;
}

/* ══════════════ 3. ECONOMIC SNAPSHOT (crypto-derived, real) ══════════════ */
function renderEcon(){
  const c = S.coins; if(!c.length) return;
  const totalMCap = c.reduce((s,x)=>s+(x.market_cap||0),0);
  const avg24 = c.reduce((s,x)=>s+(x.price_change_percentage_24h||0),0)/c.length;
  const avg7d = c.reduce((s,x)=>s+(x.price_change_percentage_7d||0),0)/c.length;
  const adv = c.filter(x=>(x.price_change_percentage_24h||0)>0).length;
  const btc = c.find(x=>x.id==='bitcoin');
  const eth = c.find(x=>x.id==='ethereum');
  const rows = [
    ['BTC dominance','Global', btc? pctDisp(btc.market_cap, totalMCap):'—', signed(btc?btc.price_change_percentage_24h:0)+'%', btc&&btc.price_change_percentage_24h>0?'up':'dn'],
    ['Bitcoin 24h','BTC', '$'+mono(btc?btc.current_price:0), pct(btc?btc.price_change_percentage_24h:0), btc&&btc.price_change_percentage_24h>0?'up':'dn'],
    ['Ethereum 24h','ETH', '$'+mono(eth?eth.current_price:0), pct(eth?eth.price_change_percentage_24h:0), eth&&eth.price_change_percentage_24h>0?'up':'dn'],
    ['Sector avg 24h','Watchlist', signed(avg24)+'%', avg24>=0?'broad gain':'broad loss', avg24>0?'up':'dn'],
    ['Sector avg 7d','Watchlist', signed(avg7d)+'%', avg7d>=0?'uptrend':'downtrend', avg7d>0?'up':'dn'],
    ['Advancers / total','24h', `${adv}/${c.length}`, adv>c.length/2?'risk-on tilt':'risk-off tilt', adv>=c.length/2?'up':'dn'],
    ['Total market cap','Watchlist', '$'+(totalMCap/1e9).toFixed(1)+'B', '', 'watch'],
  ];
  $('#econRows').innerHTML = rows.map(r=>`<tr><td>${r[0]}</td><td class="mono" style="font-size:11px">${r[1]}</td><td class="num">${r[2]}</td><td class="num ${clsDelta(parseFloat(r[3])||0)}">${r[3]}</td><td class="right"><span class="pill ${r[4]==='up'?'up':r[4]==='dn'?'dn':'watch'}">${r[4]==='up'?'BULLISH':r[4]==='dn'?'BEARISH':'NEUTRAL'}</span></td></tr>`).join('');
  $('#econSrc').textContent = 'CRYPTO-DERIVED · LIVE';
}
function pctDisp(part,total){ return (total? (part/total*100):0).toFixed(1)+'%'; }

/* ───────── Risk gauge (heuristic, labelled) ───────── */
function renderRisk(){
  const c=S.coins; if(!c.length){return;}
  const avg = c.reduce((s,x)=>s+Math.abs(x.price_change_percentage_24h||0),0)/c.length;
  const btc7 = (c.find(x=>x.id==='bitcoin')||{}).price_change_percentage_7d||0;
  // low avg move + steady 7d = calm
  let score = Math.round(Math.min(100, Math.max(4, avg*5 - btc7*0.4 + 22)));
  score = Math.max(2, Math.min(98, score));
  const val = score<40?'ok':(score<70?'warn':'crit');
  $('#riskblock').innerHTML = `
    <div class="risklabel"><span>Risk Appetite</span><span class="mono">composite</span></div>
    <div class="riskbar"><div class="riskfill" style="width:${score}%"></div></div>
    <div class="risksub">
      <span class="gauge-tag">${val==='ok'?'Calm':val==='warn'?'Caution':'Elevated'}</span>
      <span class="gauge-val ${val}">${score}<span style="font-size:11px">/100</span></span>
    </div>
    <div class="riskmeta">
      <b>Volatility score</b> derived from live 24h move magnitude &amp; 7-day BTC trend.
      Illustrative heuristic — not investment advice.
    </div>`;
}

/* ══════════════ 3b. PREDICTION MARKETS (Polymarket) & FX/METALS ══════════════ */
const _PRED_CACHE='wm_pred_cache_v1';
function predCacheGet(){ try{ const r=localStorage.getItem(_PRED_CACHE); return r? JSON.parse(r) : null; }catch(e){ return null; } }
function predCacheSet(list){ try{ localStorage.setItem(_PRED_CACHE, JSON.stringify(list)); }catch(e){ /* non-fatal */ } }

async function loadPrediction(){
  // 1) Polymarket — canonical, but its API sends no CORS headers, so it is only
  //    reachable from a browser through a working proxy. Try direct, then proxy.
  const pm = await tryPolymarket();
  if(pm && pm.length){ commitPred(pm, 'POLYMARKET · LIVE', true); return; }
  // 2) Manifold Markets — CORS-enabled, reachable directly, so the panel stays
  //    live even when no public CORS proxy is working. Active binary markets,
  //    ranked by 24h volume.
  const mf = await tryManifold();
  if(mf && mf.length){ commitPred(mf, 'MANIFOLD · LIVE', true); return; }
  // 3) Last-known snapshot — never blank on a transient failure; recovers next tick.
  const cached = predCacheGet();
  if(cached && cached.length){ commitPred(cached, 'LAST KNOWN · STALE', false); return; }
  // 4) Cold visit + every source down.
  $('#predSrc').textContent = 'OFFLINE · RETRYING';
  $('#predlist').innerHTML = `<div class="ph mono" style="padding:18px">Prediction feed unavailable right now — retrying automatically. The rest of the dashboard stays live.</div>`;
}

function commitPred(list, label, persist){
  $('#predSrc').textContent = label;
  $('#predCount').textContent = list.length + ' markets';
  renderPrediction(list);
  if(persist) predCacheSet(list);
}

async function tryPolymarket(){
  const url = 'https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume24hr&ascending=false&limit=15';
  let d = null;
  try{
    const res = await fetchTimeout(url, 9000);
    if(!res.ok) throw new Error('pm ' + res.status);
    d = await res.json();
  }catch(e){
    try{ d = await (await proxied(url)).json(); }catch(e2){ d = null; }
  }
  const arr = Array.isArray(d) ? d : [];
  const list = arr.filter(m=>{
    try{ const o = JSON.parse(m.outcomes || '[]'); return o.length === 2 && parseFloat(m.liquidity) > 0; }
    catch(e){ return false; }
  });
  return list.slice(0, 10);
}

async function tryManifold(){
  try{
    // Manifold list has no volume sort, so pull recently-active markets and rank
    // the open BINARY ones by 24h volume client-side.
    const res = await fetchTimeout('https://api.manifold.markets/v0/markets?limit=200&sort=last-bet-time', 9000);
    if(!res.ok) return null;
    const arr = await res.json(); if(!Array.isArray(arr)) return null;
    const bins = arr.filter(m => m.outcomeType === 'BINARY' && m.isResolved === false
      && typeof m.probability === 'number' && m.probability > 0.03 && m.probability < 0.97
      && (parseFloat(m.volume24Hours) || 0) > 0);
    bins.sort((a, b) => (parseFloat(b.volume24Hours) || 0) - (parseFloat(a.volume24Hours) || 0));
    return bins.slice(0, 10).map(m => ({
      question: m.question || '',
      outcomes: ['Yes', 'No'],
      // renderPrediction JSON.parses outcomePrices, so it must be a JSON string
      outcomePrices: JSON.stringify([String(m.probability), String(1 - m.probability)]),
      volume24hr: String(m.volume24Hours || ''),
      endDate: m.closeTime,   // ms epoch — renderPrediction calls new Date(endDate)
      liquidity: m.liquidity,
    }));
  }catch(e){ return null; }
}
function renderPrediction(list){
  $('#predlist').innerHTML=list.map(m=>{
    const prices=JSON.parse(m.outcomePrices||'[0]');
    const yes=parseFloat(prices[0]); const prob=Math.round((isFinite(yes)?yes:0)*100);
    const dy=parseFloat(m.oneDayPriceChange)||0; const dyCls=dy>0?'up':(dy<0?'dn':'');
    const vol=$vol(m.volume24hr);
    const end=m.endDate? new Date(m.endDate).toISOString().slice(0,10):'';
    const pcol=prob>=60?'var(--green)':(prob<=40?'var(--red)':'var(--amber)');
    return `<div class="prow">
      <div class="pq"><span class="p" style="color:${pcol}">${prob}%</span><span>${esc(m.question||'')}</span></div>
      <div class="pbar"><span class="yes" style="width:${Math.max(0,Math.min(100,prob))}%"></span><span class="no"></span></div>
      <div class="pmeta"><span>24h vol <b class="vol">${vol}</b></span><span>${end?'ends '+end:''}</span>${dy?`<span class="dy ${dyCls}">${dy>0?'+':''}${(dy*100).toFixed(1)} pts 24h</span>`:''}</div>
    </div>`;
  }).join('');
}
const $vol=v=>{ v=parseFloat(v)||0; return v>=1e9?'$'+(v/1e9).toFixed(2)+'B':(v>=1e6?'$'+(v/1e6).toFixed(1)+'M':(v>=1e3?'$'+(v/1e3).toFixed(1)+'K':'$'+Math.round(v).toLocaleString())); };

const FXDEF=[['EUR/USD','EUR',0],['GBP/USD','GBP',0],['USD/JPY','JPY',1],['USD/CHF','CHF',1],['USD/CAD','CAD',1],['AUD/USD','AUD',0]];
async function loadFX(){
  const to=FXDEF.map(x=>x[1]).join(',');
  const now=new Date(); const start=new Date(Date.now()-7*864e5).toISOString().slice(0,10);
  const end=now.toISOString().slice(0,10);
  let fx=null, hist=null, gold=null;
  try{
    const [lr,hr,gr]=await Promise.all([
      fetchTimeout(`https://api.frankfurter.dev/v1/latest?base=USD&symbols=${to}`,7000).then(r=>r.ok?r.json():null).catch(()=>null),
      fetchTimeout(`https://api.frankfurter.dev/v1/${start}..${end}?base=USD&symbols=${to}`,7000).then(r=>r.ok?r.json():null).catch(()=>null),
      fetchTimeout('https://api.gold-api.com/price/XAU',6000).then(r=>r.ok?r.json():null).catch(()=>null)
    ]);
    fx=lr; hist=hr; gold=gr;
  }catch(e){}
  if(!fx || !fx.rates){
    $('#fxSrc').textContent='OFFLINE · SAMPLE';
    $('#fxgold').innerHTML=`<div class="ph mono" style="padding:18px">FX/metals unreachable — retrying automatically.</div>`;
    return;
  }
  renderFX(fx,hist,gold);
  $('#fxSrc').textContent='ECB + GOLDAPI · LIVE';
}
function fxVal(r,direct){ return direct? r : 1/r; }
function fxFmt(v){ return v>=100? v.toFixed(1) : v>=10? v.toFixed(3) : v>=1? v.toFixed(4) : v.toFixed(4); }
function renderFX(fx,hist,gold){
  const dates=hist&&hist.rates? Object.keys(hist.rates).sort():[];
  const prevDate= dates.length>=2? dates[dates.length-2]: null;
  const prevRates= prevDate&&hist? hist.rates[prevDate]: null;
  const goldHtml= gold&&gold.price
    ? `<div class="goldtile"><div class="gn">Gold · XAU/USD</div><div class="gp">$${mono(gold.price)}</div><div class="gmeta">${esc(gold.updatedAtReadable||gold.updatedAt||'')} · per troy oz</div></div>`
    : `<div class="ph mono">Gold offline</div>`;
  const rows=FXDEF.map(([pair,cur,direct])=>{
    const r=parseFloat(fx.rates[cur]); if(!isFinite(r)||!r) return '';
    const v=fxVal(r,direct);
    let chg=0;
    if(prevRates && prevRates[cur]!=null){ const pv=fxVal(parseFloat(prevRates[cur]),direct); chg=(v-pv)/pv*100; }
    const cls=chg>0.0001?'up':(chg<-0.0001?'dn':'flat');
    return `<div class="fxrow"><span class="c">${pair}</span><span class="r">${fxFmt(v)}</span><span class="ch ${cls}">${chg!==0?(chg>0?'+':'')+chg.toFixed(2)+'%':''}</span></div>`;
  }).filter(Boolean).join('');
  $('#fxgold').innerHTML=`${goldHtml}<div class="fxrows">${rows}</div>`;
}

/* ── FiatLeak movers (fiatleak.js, refreshed hourly by a scraper cron) ── */
function flPct(v){ return (v>=0?'+':'')+Number(v).toFixed(2)+'%'; }
function renderFiatleak(){
  const box=$('#flRows'); if(!box) return;
  const F=window.FIATLEAK;
  $('#flSrc').textContent = (F && F._updated) ? 'FIATLEAK · '+F._updated : 'FIATLEAK';
  if(!F || !F.assets){
    box.innerHTML='<div class="ph mono">FiatLeak data not loaded yet.</div>';
    return;
  }
  const b=F.breadth||{};
  $('#flBreadth').textContent = (b.g!=null) ? b.g+'↑ / '+b.l+'↓' : '';
  const chip=(s,v)=>`<span class="flchip ${v>=0?'up':'dn'}"><span class="fls">${s}</span>${flPct(v)}</span>`;
  const gain=(F.topGainers||[]).map(([s,v])=>chip(s,v)).join('');
  const loss=(F.topLosers||[]).map(([s,v])=>chip(s,v)).join('');
  const marq=Object.keys(F.marquee||{}).map(s=>{ const a=F.marquee[s]; return `<span class="flprice ${a[1]>=0?'up':'dn'}"><span class="fls">${s}</span><b>$${a[0]}</b>${flPct(a[1])}</span>`; }).join('');
  box.innerHTML =
    `<div class="flhalf"><div class="flmh">TOP GAINERS</div><div class="flm">${gain||'<span class="muted">none</span>'}</div>`+
    `<div class="flmh">TOP LOSERS</div><div class="flm">${loss||'<span class="muted">none</span>'}</div></div>`+
    `<div class="flhalf flp"><div class="flmh">KEY PRICES · CRYPTO + US STOCKS</div><div class="flm marq">${marq||'<span class="muted">n/a</span>'}</div></div>`;
}
async function refreshFiatleak(){
  try{
    const r=await fetchTimeout('fiatleak.js?t='+Date.now(),8000);
    if(r.ok){
      const txt=await r.text();
      const scope={}; new Function('window', txt)(scope);   // fiatleak.js does window.FIATLEAK=…
      if(scope.FIATLEAK && scope.FIATLEAK.assets) window.FIATLEAK=scope.FIATLEAK;
    }
  }catch(e){ /* keep last */ }
  renderFiatleak();
}

/* ══════════════ 4. INTEL FEED (news RSS, best-effort) ══════════════ */
const NEWS_FEEDS = [
  { region:'World', src:'Google News', url:'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en' },
  { region:'Markets', src:'Google News', url:'https://news.google.com/rss/search?q=global%20markets%20economy&hl=en-US&gl=US&ceid=US:en' },
  { region:'Cyber', src:'Google News', url:'https://news.google.com/rss/search?q=cybersecurity%20hack%20breach&hl=en-US&gl=US&ceid=US:en' },
  { region:'Geo', src:'Google News', url:'https://news.google.com/rss/search?q=geopolitics%20diplomacy&hl=en-US&gl=US&ceid=US:en' },
  { region:'Energy', src:'Google News', url:'https://news.google.com/rss/search?q=oil%20energy%20commodities&hl=en-US&gl=US&ceid=US:en' },
  // ── Independent / no-paywall outlets (direct feeds) ──
  // Journalism you can actually open, without the hard paywalls that Google News
  // aggregation keeps mixing in. Deliberately diverse: multiple geographies and
  // editorial stances so no single outlet (or one leaning) owns any story.
  { region:'World', src:'Al Jazeera', url:'https://www.aljazeera.com/xml/rss/all.xml' },
  { region:'World', src:'France 24', url:'https://www.france24.com/en/rss' },
  { region:'World', src:'The Conversation', url:'https://theconversation.com/us/articles.atom' },
  { region:'World', src:'Middle East Eye', url:'https://www.middleeasteye.net/rss' },
  { region:'World', src:'RFI', url:'https://www.rfi.fr/en/rss' },
  { region:'US', src:'ProPublica', url:'https://www.propublica.org/feeds/propublica/main' },
  { region:'US', src:'The Intercept', url:'https://theintercept.com/feed/?rss' },
  { region:'US', src:'Democracy Now', url:'https://www.democracynow.org/democracynow.rss' },
  { region:'US', src:'Reason', url:'https://reason.com/feed/' },
  { region:'Climate', src:'Grist', url:'https://grist.org/feed/' },
  { region:'Cyber',   src:'404 Media',       url:'https://www.404media.co/rss/' },
  // ── Expanded coverage (every URL below verified reachable with items) ──
  // Europe / Russia / ANZ
  { region:'Europe',  src:'DW',               url:'https://rss.dw.com/rdf/rss-en-all' },
  { region:'Europe',  src:'The Guardian',     url:'https://www.theguardian.com/world/rss' },
  { region:'Europe',  src:'El País',          url:'https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada' },
  { region:'Europe',  src:'Meduza',           url:'https://meduza.io/rss/en/all' },
  { region:'Europe',  src:'The Moscow Times', url:'https://www.themoscowtimes.com/rss/news' },
  { region:'Europe',  src:'TASS',             url:'https://tass.com/rss/v2.xml' },
  { region:'Europe',  src:'CBC World',        url:'https://www.cbc.ca/webfeed/rss/rss-world' },
  { region:'Europe',  src:'ABC Australia',    url:'https://www.abc.net.au/news/feed/51120/rss.xml' },
  { region:'World',   src:'NPR',              url:'https://feeds.npr.org/1004/rss.xml' },
  // Middle East / South & East Asia / Africa
  { region:'Mideast', src:'Times of Israel',  url:'https://www.timesofisrael.com/feed/' },
  { region:'Mideast', src:'Al-Monitor',       url:'https://www.al-monitor.com/rss' },
  { region:'Mideast', src:'Tehran Times',     url:'https://www.tehrantimes.com/rss' },
  { region:'Mideast', src:'Anadolu Agency',   url:'https://www.aa.com.tr/en/rss/default?cat=guncel' },
  { region:'Asia',    src:'Dawn',             url:'https://www.dawn.com/feeds/home' },
  { region:'Asia',    src:'Channel NewsAsia', url:'https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml' },
  { region:'Asia',    src:'Bangkok Post',     url:'https://www.bangkokpost.com/rss/data/topstories.xml' },
  { region:'Africa',  src:'Premium Times',    url:'https://www.premiumtimesng.com/feed' },
  // Humanitarian / disaster / health — these also feed the World map
  { region:'Disaster',src:'ReliefWeb',        url:'https://reliefweb.int/updates/rss.xml' },
  { region:'Disaster',src:'GDACS',            url:'https://www.gdacs.org/xml/rss.xml' },
  { region:'Disaster',src:'FloodList',        url:'https://floodlist.com/feed' },
  { region:'Disaster',src:'Smithsonian GVP',  url:'https://volcano.si.edu/news/WeeklyVolcanoRSS.xml' },
  { region:'Health',  src:'WHO',              url:'https://www.who.int/rss-feeds/news-english.xml' },
  { region:'World',   src:'UN News',          url:'https://news.un.org/feed/subscribe/en/news/all/rss.xml' },
  // Security / cyber incident reporting
  { region:'Security',src:'Bellingcat',       url:'https://www.bellingcat.com/feed/' },
  { region:'Security',src:'The Record',       url:'https://therecord.media/feed' },
  { region:'Cyber',   src:'Krebs on Security',url:'https://krebsonsecurity.com/feed/' },
  { region:'Cyber',   src:'BleepingComputer', url:'https://www.bleepingcomputer.com/feed/' },
  { region:'Cyber',   src:'CISA Advisories',  url:'https://www.cisa.gov/cybersecurity-advisories/all.xml' },
  { region:'Cyber',   src:'SANS ISC',         url:'https://isc.sans.edu/rssfeed.xml' },
  // Energy / shipping / climate / space
  { region:'Energy',  src:'OilPrice',         url:'https://oilprice.com/rss/main' },
  { region:'Energy',  src:'gCaptain',         url:'https://gcaptain.com/feed/' },
  { region:'Climate', src:'Carbon Brief',     url:'https://www.carbonbrief.org/feed' },
  { region:'Space',   src:'Spaceflight Now',  url:'https://spaceflightnow.com/feed/' },
  { region:'Space',   src:'NASA',             url:'https://www.nasa.gov/rss/dyn/breaking_news.rss' },
  // Contact/FIGU-adjacent commentary — free, full-text, no paywall. Single-outlet
  // beat (Plejaren / Billy Meier case reporting), kept as its own region tag so it
  // reads as one voice rather than generic world coverage.
  { region:'FIGU',   src:'They Fly Blog', url:'https://theyflyblog.com/feed/' },
];
const SAMPLE_ITEMS = [
  {title:'Live feeds unreachable — sample item. Markets &amp; clocks remain live.', when:'now', region:'World', src:'SAMPLE', cat:'flat'},
];
// Outlets that hard-paywall their articles. Drop their items so every feed & alert
// link opens a source you can actually read. Matched word-boundary against the
// outlet name Google News attaches to each item.
const PAYWALLED = [
  // US national
  'new york times','nytimes','nyt','wall street journal','wsj','bloomberg','financial times',
  'the economist','washington post','the atlantic','barron','the information',
  'foreign policy','harvard business review','wired','new yorker','los angeles times',
  'chicago tribune','the new republic','american prospect',
  'the week','the dispatch','punchbowl news','the free press','the bulwark',
  'cook political report','foreign affairs','commentary',
  'new york review of books','london review of books','new scientist','spectator',
  'new statesman','prospect magazine','the times','sunday times','the telegraph',
  // US regional (mostly hard paywalled)
  'boston globe','philadelphia inquirer','seattle times','star tribune','st. louis post-dispatch',
  'post-dispatch','denver post','miami herald','sacramento bee','baltimore banner','news & observer',
  // US trade / entertainment / media
  'variety','hollywood reporter','business of fashion','stat news','statnews',
  // Business
  'nikkei','caixin','the australian','business insider','sydney morning herald','the age',
  'forbes','ft.com',
  // International
  'south china morning post','scmp','times of india','hindustan times','economic times',
  'livemint','the hindu','the globe and mail','national post','toronto star','la presse',
  'le monde','le figaro','handelsblatt','frankfurter allgemeine','der spiegel',
  'neue zuercher zeitung','il sole 24 ore','corriere della sera','haaretz','japan times',
  'asahi shimbun'
];
// Free outlets whose name happens to contain a paywalled substring and must
// never be dropped (e.g. "The Times of Israel" contains the "the times" token,
// but is a free site). Runs before the paywall match. Only list genuinely free
// outlets — do NOT list paywalled ones (Times of India, Hindustan Times,
// Economic Times, etc. are real paywalls and stay blocked).
const _FREE_SAFE = ['times of israel'];
const _pwRe = PAYWALLED.map(w=>new RegExp('(^|[^a-z0-9])'+w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'([^a-z0-9]|$)'));
function isPaywalled(src){
  const s=(src||'').toLowerCase().trim();
  if(!s) return false;
  if(_FREE_SAFE.some(g=>s.includes(g))) return false;
  return _pwRe.some(r=>r.test(s));
}
// Outlet label for a feed card. Direct-RSS outlets carry their own name in `src`,
// while `source` falls back to whatever the feed put in <dc:creator>/<author>
// (e.g. the blogger's initials or the RFI journalist's byline). Prefer the outlet
// name for those; keep `source` for the Google News aggregate, where it is the
// actual publishing outlet.
function outletLabel(it){
  const src=(it.src||'').trim();
  if(src && src!=='Google News') return src;
  return (it.source||'').trim() || src;
}

// Pull raw RSS/Atom text live: try direct (for any CORS-enabled feed), then via
// public CORS proxies. allorigins /get wraps the body in {"contents":...} and is
// currently the most reliable route, so unwrap it. Returns null if unreachable.
const _RSS_PROXIES = [
  'https://api.allorigins.win/get?url=',
  'https://api.allorigins.win/raw?url=',
  'https://api.codetabs.com/v1/proxy?quest=',
  'https://corsproxy.io/?url=',
  'https://api.cors.lol/?url=',
  'https://cors.eu.org/',
];
async function fetchRssLive(url){
  try{ const r=await fetchTimeout(url,9000); if(r.ok){ const t=await r.text(); if(t && /<(rss|feed|item|entry)\b/.test(t)) return t; } }catch(e){}
  const target=encodeURIComponent(url);
  for(const base of _RSS_PROXIES){
    try{
      const r=await fetchTimeout(base+target,8000);
      if(!r.ok) continue;
      let t=await r.text(); if(!t) continue;
      const ct=t.trim();
      if(ct.startsWith('{')){ const j=JSON.parse(ct); t=(j && typeof j.contents==='string')?j.contents:''; }
      if(t && /<(rss|feed|item|entry)\b/.test(t)) return t;
    }catch(e){}
  }
  return null;
}
// fetch one feed fresh through the live route above (hits the outlet live => freshest)
async function fetchFeedProxy(f){
  const xml = await fetchRssLive(f.url);
  if(!xml) return [];
  const doc = new DOMParser().parseFromString(xml,'text/xml');
  const now = Date.now();
  return Array.from(doc.getElementsByTagName('item')).slice(0,20).map(it=>{
    let title=(it.querySelector('title')||{}).textContent||'';
    let source=(it.querySelector('source')||{}).textContent||'';
    const m=title.match(/\s-\s([^-]+)$/);
    if(m && !source){ source=m[1].trim(); title=title.slice(0,m.index).trim(); }
    const pub=(it.querySelector('pubDate')||{}).textContent||'';
    const rawTs=parseTs(pub);
    const ts = isNaN(rawTs) ? 0 : rawTs;    // undatable -> oldest, no fake 'now'
    return { title, source: source||'RSS', link:(it.querySelector('link')||{}).textContent||'', ts, ago: agoLabel(ts, now) };
  }).filter(x=>x.title && !isPaywalled(x.source));
}
// fallback: the same feed through the rss2json gateway (CORS, no key) if the live
// route fails. Note rss2json caches ~hours and caps items, so this is secondary.
async function fetchFeedJSON(f){
  const u = 'https://api.rss2json.com/v1/api.json?rss_url=' + encodeURIComponent(f.url);
  const res = await fetchTimeout(u);
  if(!res.ok) throw new Error('rss2json '+res.status);
  const d = await res.json();
  if(d.status!=='ok') throw new Error('rss2json status');
  const now = Date.now();
  return (d.items||[]).map(it=>{
    let title=(it.title||'').trim(); let source=(it.source||'').trim();
    if(!source){ const m=title.match(/\s-\s([^-]+)$/); if(m){ source=m[1].trim(); title=title.slice(0,m.index).trim(); } }
    const rawTs=parseTs(it.pubDate);
    const ts = isNaN(rawTs) ? 0 : rawTs;    // undatable -> oldest, no fake 'now'
    return { title, source: source||'RSS', link: it.link||'', ts, ago: agoLabel(ts, now) };
  }).filter(x=>x.title && !isPaywalled(x.source));
}
// Freshness window for the committed server-side snapshot (news.js). The cron
// rewrites it every ~30 min, so anything older than this means the scheduler is
// down or the file is absent — fall back to the live proxy/JSON path then.
const NEWS_SNAPSHOT_MAX_AGE = 4 * 60 * 60 * 1000;
function loadNewsFromSnapshot(){
  // Returns {items, via} from window.NEWS if it is present and fresh enough,
  // else null. Recomputes per-item 'ago' against now so age labels stay live
  // even though the snapshot is a committed static file.
  const N = window.NEWS;
  if(!N || !Array.isArray(N.items) || !N.items.length) return null;
  let stamp = 0;
  if(typeof N._updated === 'string'){
    const m = N._updated.replace('UTC','').trim().match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
    if(m) stamp = Date.parse(m[1]+'T'+m[2]+':00Z');
  }
  if(!(stamp > 0) || (Date.now() - stamp) > NEWS_SNAPSHOT_MAX_AGE) return null;
  const now = Date.now();
  const items = N.items
    .map(it => ({ title: it.title, source: it.source, link: it.link,
                  ts: it.ts, region: it.region, src: it.src,
                  ago: agoLabel(it.ts, now) }))
    .filter(x => x.title && !isPaywalled(x.source));
  return { items, via: 'SNAPSHOT' };
}
// ── Public social signals (Telegram / Reddit / X) ────────────────────────────
// Fetched server-side by fetch_social.py into social.js (window.SOCIAL) and read
// same-origin here. These are UNVERIFIED first reports, not edited journalism:
// Telegram comes from public channel previews, Reddit from public Atom feeds, and
// X from Twitter's own public timeline widget — which is cached per handle, so a
// stale handle simply contributes nothing. Everything is freshness-gated below so
// a cached post is never presented as new.
const SOCIAL_MAX_AGE = { TELEGRAM: 72*60*60*1000, REDDIT: 48*60*60*1000, X: 7*24*60*60*1000 };
function loadSocialFromSnapshot(){
  const D = window.SOCIAL;
  if(!D || !Array.isArray(D.items) || !D.items.length) return [];
  const now = Date.now();
  return D.items
    .filter(it => it && it.title)
    .filter(it => platformEnabled(it.region))      // Settings: per-platform switches
    .filter(it => (now - (it.ts||0)) <= (SOCIAL_MAX_AGE[it.region] || 48*60*60*1000))
    .map(it => ({ title: it.title, source: it.source, link: it.link, ts: it.ts,
                  region: it.region || 'SOCIAL', src: it.src || it.source || 'Social',
                  platform: it.platform || it.region || 'SOCIAL', ago: agoLabel(it.ts, now) }));
}
// Balanced feed selection. A flat newest-N slice lets the highest-volume wire
// (Google News runs ~100 items/day) own the whole panel: a low-volume outlet —
// a blog that posts twice a week — never survives the cut, no matter how fresh
// its latest post is. Round-robin by source with a per-source cap keeps the
// panel genuinely multi-outlet; any slots left over are filled by pure recency.
function balancedFeed(list, perSource, max){
  const bySrc = new Map();
  for(const it of list){
    const k = it.src || it.source || 'News';
    if(!bySrc.has(k)) bySrc.set(k, []);
    bySrc.get(k).push(it);
  }
  const out=[], taken=new Set();
  // pass 1: every source gets its first slot before any source gets a second
  for(let round=0; round<perSource && out.length<max; round++){
    for(const arr of bySrc.values()){
      if(round < arr.length && out.length < max){ out.push(arr[round]); taken.add(arr[round]); }
    }
  }
  // pass 2: fill remaining slots by recency
  for(const it of list){
    if(out.length>=max) break;
    if(!taken.has(it)){ out.push(it); taken.add(it); }
  }
  return out.sort((a,b)=>b.ts-a.ts);
}
async function loadNews(){
  $('#intelSrc').textContent = 'CONTACTING…';
  let items=[]; let via='';
  // Preferred path: committed server-side snapshot (news.js) — instant and
  // independent of flaky public CORS proxies. Only if it is absent/stale do we
  // race the live proxy/JSON channels.
  const snap = loadNewsFromSnapshot();
  if(snap){
    items = snap.items; via = 'SNAPSHOT';
  }else{
    // Per feed, race a fresh CORS-proxy fetch against the rss2json fallback at the
    // same time (both bounded individually) and prefer the fresh proxy result when
    // it yields items. Everything runs in parallel, so the whole pass resolves in a
    // few seconds rather than one slow channel holding up the panel.
    const settled = await Promise.all(NEWS_FEEDS.map(async f=>{
      const [proxyRes, jsonRes] = await Promise.all([
        fetchFeedProxy(f).catch(()=>null),
        fetchFeedJSON(f).catch(()=>null)
      ]);
      const useProxy = proxyRes && proxyRes.length;
      return { via: useProxy?'PROXY':'JSON', list: (useProxy?proxyRes:jsonRes) || [] };
    }));
    let proxFeeds=0;
    settled.forEach((r,i)=>{
      if(r.list && r.list.length){ if(r.via==='PROXY') proxFeeds++; items.push(...r.list.map(it=>({...it, region:NEWS_FEEDS[i].region, src:NEWS_FEEDS[i].src}))); }
    });
    via = items.length ? (proxFeeds?'PROXY':'JSON') : '';
  }
  // Merge the committed public social snapshot (Telegram / Reddit / X) into the
  // same pool so those outlets appear as ordinary feed cards, tagged by platform.
  // Each platform has already been freshness-gated on its own window.
  const social = loadSocialFromSnapshot();
  if(social.length){
    items = items.concat(social);
    via = via ? via + '+SOCIAL' : 'SOCIAL';
  }
  if(!items.length){
    S.news = SAMPLE_ITEMS.map(it=>({...it,when:'now',ago:'0m'}));
    $('#intelSrc').textContent = 'RSS UNREACHABLE · SAMPLE';
  }else{
    // dedupe by title; sort newest-first; drop ancient leftovers so feed & map are live
    const cutoff = Date.now() - 48*60*60*1000;
    const seen = new Set();
    // social items carry their own (longer) platform freshness window — don't
    // re-cut them at the 48h news horizon.
    const recent = items.filter(it=> it.platform || it.ts>=cutoff)
      .sort((a,b)=>b.ts-a.ts)
      .filter(it=>{ const k=(it.title||'').toLowerCase().trim(); if(!k||seen.has(k)) return false; seen.add(k); return true; });
    // Region focus (Settings): filtered before the balanced selection so a chosen
    // subset still gets one slot per source rather than surviving on luck. An empty
    // selection means "everything".
    const pool = SET.regions.length ? recent.filter(it=>SET.regions.indexOf(it.region || 'News') >= 0) : recent;
    S.news = balancedFeed(pool.length ? pool : recent, 3, 90);
    if(SET.regions.length && !pool.length){
      $('#intelSrc').textContent = 'LIVE · NO ITEMS IN FOCUS REGIONS';
    }else{
      $('#intelSrc').textContent = 'LIVE · ' + (via || 'FEED') + (SET.regions.length ? ' · FOCUS' : '');
    }
    setStatus(true, 'STATUS: ONLINE — MARKETS + INTEL LIVE');
  }
  $('#feedFresh').textContent = 'updated '+new Date().toLocaleTimeString('en-GB');
  // Prophecy source selection: use the richer AUTHORED causal analyses
  // (prophecy-authors.js, written a few times a day by the scheduled causal
  // job from this feed) while they are fresh; otherwise fall back to the
  // always-on in-browser live engine (live-prophesy.js). Coverage counts are
  // always recomputed live against the current headlines either way.
  try{
    const AUTH = window.PROPHECIES_AUTHORED || null;
    const STAMP = window.PROPHECIES_AUTHORED_STAMP || '';
    let fresh = false;
    if(AUTH && AUTH.length && STAMP){
      const t = new Date(STAMP.replace(' ', 'T') + (/:00$/.test(STAMP) ? '' : ':00'));
      fresh = !isNaN(t) && (Date.now() - t.getTime()) < 24 * 60 * 60 * 1000;
    }
    if(fresh && AUTH && AUTH.length){
      window.PROPHECIES = Object.assign(AUTH.slice(), { _updated: STAMP });
    } else if(typeof window.buildLiveProphecies === 'function'){
      const live = window.buildLiveProphecies(S.news);
      live._updated = new Date().toLocaleString('en-GB');
      window.PROPHECIES = live;
    } else {
      window.PROPHECIES = [];
    }
  }catch(e){ /* keep last good list */ }
  // Render each dependent panel independently so one panel bug never blanks the rest.
  [renderFeed, renderAlerts, renderAmber, renderFloods, renderOutbreaks, renderDefcon, renderBrief, renderWorld, renderProphecy].forEach(fn=>{ try{ fn(); }catch(e){ /* isolate */ } });
}
function renderFeed(){
  // Slot guarantee: take one (newest) item per source first, then fill the rest
  // by recency, then sort the selection newest-first so the list still reads
  // chronologically. Without this a two-posts-a-week outlet can never outrank
  // the wire on a 30-slot panel, so it silently never appears. The cap is set
  // above the outlet count so every configured source gets a slot each cycle.
  const list = balancedFeed(S.news, 3, 60);
  $('#feedCount').textContent = list.length + (S.news.length>list.length?'+':list.length===1?' item':' items');
  $('#feed').innerHTML = list.map(it=>`
    <a class="fitem${it.platform?' social':''}" href="${esc(it.link)}" target="_blank" rel="noopener">
      <span class="when">${it.ago}</span>
      <span class="felem">
        <div class="ftitle">${esc(it.title)}</div>
        <div class="fmeta">
          <span class="tag region">${esc(it.region||'News')}</span>
          <span class="tag src">${esc(outletLabel(it))}</span>
          ${it.platform?`<span class="tag unverified" title="Unverified public ${esc(it.platform)} post — first report, not edited journalism">unverified</span>`:''}
        </div>
      </span>
    </a>`).join('');
}

/* ══════════════ 5. ALERTS ══════════════ */
const ALERT_KEYWORDS = [
  {k:'cyber|hack|breach|ransom|leak', sev:'high', label:'CYBER'},
  {k:'war|milit|conflict|attack|strike|invasion', sev:'high', label:'SECURITY'},
  {k:'sanction|tariff|trade war|embargo', sev:'mid', label:'TRADE'},
  {k:'energy|oil|gas|supply', sev:'mid', label:'ENERGY'},
  {k:'crash|plunge|slump|rout|tumble', sev:'high', label:'MARKET'},
  {k:'rally|surge|record high', sev:'low', label:'MARKET'},
  {k:'rate|inflation|central bank', sev:'mid', label:'MACRO'},
];
function renderAlerts(){
  const alerts=[];
  // Real seismic events first: measured magnitude/depth from USGS, not keyword
  // inference. M4.5+ within 48h, strongest first — a quake is a fact with a
  // timestamp, so it outranks anything derived from a headline.
  const Q = window.QUAKES;
  if(Q && Array.isArray(Q.quakes)){
    const qcut = Date.now() - 48*60*60*1000;
    Q.quakes.filter(q=>q.mag>=4.5 && (q.ts||0)>=qcut)
      .sort((a,b)=>b.mag-a.mag).slice(0,6).forEach(q=>{
        alerts.push({sev: q.mag>=6?'high':'mid', label:'SEISMIC', fast:true,
                     title:'M'+q.mag+' — '+q.place+(q.depth!=null?' · depth '+q.depth+' km':'')+
                           (q.tsunami?' · TSUNAMI FLAG':''),
                     when: agoLabel(q.ts, Date.now()), src:'USGS', link:q.url||''});
      });
  }
  S.news.forEach(it=>{
    const t=(it.title||'').toLowerCase()+' '+(it.region||'').toLowerCase();
    for(const a of ALERT_KEYWORDS){
      if(new RegExp(a.k).test(t)){
        alerts.push({sev:a.sev,label:a.label,title:it.title,when:it.ago,src:it.source,link:it.link||''});
        break;
      }
    }
  });
  const sevRank={high:0,mid:1,low:2};
  // Measured events (seismic) lead the list within their severity band.
  const top = alerts.slice(0,20).sort((x,y)=>(sevRank[x.sev]-sevRank[y.sev]) || ((y.fast?1:0)-(x.fast?1:0))).slice(0,14);
  const sevTxt={high:'HIGH',mid:'MED',low:'LOW'};
  const cell = a => a.link
    ? `<a class="alert sev-${a.sev} alertlink" href="${esc(a.link)}" target="_blank" rel="noopener">
        <span class="sev">${a.label}</span>
        <span class="at">${a.when}</span>
        <div class="ab">
          <div class="atitle">${esc(a.title)}</div>
          <div class="asrc">${sevTxt[a.sev]} PRIORITY · ${esc(a.src||'')} · open ↗</div>
        </div>
      </a>`
    : `<div class="alert sev-${a.sev}">
        <span class="sev">${a.label}</span>
        <span class="at">${a.when}</span>
        <div class="ab">
          <div class="atitle">${esc(a.title)}</div>
          <div class="asrc">${sevTxt[a.sev]} PRIORITY · ${esc(a.src||'')}</div>
        </div>
      </div>`;
  $('#alertCount').textContent = top.length ? top.length+' active' : '0 active';
  $('#alertlist').innerHTML = top.length? top.map(cell).join('') : `<div class="ph mono" style="padding:18px">No priority alerts in current feed.</div>`;
}

/* ══════════════ 5b. AMBER (NCMEC missing-child alerts, real data) ══════════════ */
function renderAmber(){
  const A = window.AMBER;
  const bar = $('#amberbar');
  const countEl = $('#amberCount'); const srcEl = $('#amberSrc');
  if(!bar){ return; }
  if(!A || !Array.isArray(A.cases) || !A.cases.length){
    if(countEl) countEl.textContent='0 active';
    if(srcEl) srcEl.textContent='NCMEC · OFFLINE';
    bar.innerHTML = `<div class="ph mono" style="padding:16px">Missing-child alert feed unavailable right now — retrying on next refresh. If this persists, the NCMEC feed is unreachable from this network.</div>`;
    return;
  }
  const cases = A.cases;
  if(countEl) countEl.textContent = cases.length+' active';
  if(srcEl) srcEl.textContent = 'NCMEC · '+(A._updated||'').split(' ')[0];
  const item = c => `
    <div class="amberitem">
      <div class="amflag">◉</div>
      <div class="ambody">
        <div class="amtitle"><b>${esc(c.name)}</b>${c.age!=null?' · age now '+c.age:''}</div>
        <div class="ammeta">Missing from <b>${esc(c.loc||c.city||'Location undisclosed')}</b>${c.missing?' · '+esc(c.missing):''}</div>
        <div class="amsrc">Real case · NCMEC missing-children registry · ${c.link?`<a href="${esc(c.link)}" target="_blank" rel="noopener">poster ↗</a>`:'source: NCMEC'} · Report tips: 1-800-THE-LOST</div>
      </div>
    </div>`;
  bar.innerHTML = cases.slice(0,12).map(item).join('');
  // coverage honesty: never claim this US-anchored feed is worldwide
  const note = document.getElementById('amberCoverage');
  if(note) note.textContent = 'Coverage: NCMEC missing-child alert cases (US-anchored registry). Not a global AMBER-activation feed — verify locally.';
}

/* ══════════════ 5c. FLOOD REPORT (GDACS global + NOAA/NWS, real data) ══════════════ */
function floodRank(l){ return l === 'Red' ? 0 : (l === 'Orange' ? 1 : 2); }
function renderFloods(){
  const bar = $('#floodlist'); if(!bar) return;
  const F = window.FLOODS;
  const cEl = $('#floodCount'), sEl = $('#floodSrc');
  if(!F || !Array.isArray(F.events) || !F.events.length){
    if(cEl) cEl.textContent = '0 active';
    if(sEl) sEl.textContent = 'GDACS · OFFLINE';
    bar.innerHTML = `<div class="ph mono" style="padding:16px">Flood feed unavailable right now — retrying on next refresh. If this persists the GDACS/NWS feeds are unreachable.</div>`;
    return;
  }
  const ev = F.events.slice().sort((a,b)=> floodRank(a.level) - floodRank(b.level)
              || String(b.from||'').localeCompare(String(a.from||'')));
  if(cEl) cEl.textContent = F.global + ' global' + (F.usWarnings ? ' · ' + F.usWarnings + ' US' : '');
  if(sEl) sEl.textContent = 'GDACS · ' + String(F._updated||'').slice(0,10);
  const chip = l => {
    const c = l === 'Red' ? 'fl-red' : (l === 'Orange' ? 'fl-orange' : 'fl-green');
    return `<span class="fllevel ${c}">${esc(l)}</span>`;
  };
  bar.innerHTML = ev.slice(0,10).map(e=>`
    <div class="flitem">
      ${chip(e.level)}
      <div class="flbody">
        <div class="fltitle">${esc(e.name)}</div>
        <div class="flmeta">${esc(e.country || 'Location undisclosed')}${e.from ? ' · ' + esc(e.from) + (e.to ? ' → ' + esc(e.to) : '') : ''}</div>
        <div class="flsrc">Real event · GDACS global flood alerting${e.report ? ` · <a href="${esc(e.report)}" target="_blank" rel="noopener">report ↗</a>` : ''}</div>
      </div>
    </div>`).join('')
    + `<div class="flnote">${F.global} active global flood alerts — ${F.red} red · ${F.orange} orange across ${(F.countries||[]).length} countries.`
    + ` US: ${F.usWarnings} NWS flood warning${F.usWarnings === 1 ? '' : 's'}. Source: GDACS (EU JRC) + NOAA/NWS.</div>`;
}

/* ══════════════ 5e. OUTBREAK REPORT (WHO Disease Outbreak News, real data) ══════════════ */
function renderOutbreaks(){
  const bar = $('#outbreaklist'); if(!bar) return;
  const O = window.OUTBREAKS;
  const cEl = $('#outbreakCount'), sEl = $('#outbreakSrc');
  if(!O || !Array.isArray(O.items) || !O.items.length){
    if(cEl) cEl.textContent = '0 reports';
    if(sEl) sEl.textContent = 'WHO · OFFLINE';
    bar.innerHTML = `<div class="ph mono" style="padding:16px">Outbreak feed unavailable right now — retrying on next refresh. If this persists the WHO DON feed is unreachable.</div>`;
    return;
  }
  // only current bulletins: WHO DON is an archive, so keep the last 120 days and
  // surface older ones as an explicit archive count rather than as "live" reports
  const nowMs = Date.now();
  const recent = O.items.filter(o => {
    const t = Date.parse(o.date || '');
    return isNaN(t) || (nowMs - t) <= 120 * 24 * 3600e3;
  });
  const archive = O.items.length - recent.length;
  if(cEl) cEl.textContent = recent.length + ' recent' + (O.countries ? ' · ' + O.countries.length + ' countries' : '');
  if(sEl) sEl.textContent = 'WHO DON · ' + String(O.latest || O._updated || '').slice(0, 10);
  const items = recent.slice(0, 12);
  if(!items.length){
    bar.innerHTML = `<div class="ph mono" style="padding:16px">No WHO outbreak bulletins in the last 120 days — ${archive} older bulletins sit in the WHO archive.</div>`;
    return;
  }
  bar.innerHTML = items.map(o=>`
    <div class="obitem">
      <div class="obflag">☣</div>
      <div class="obbody">
        <div class="obtitle">${esc(o.disease || o.title)}</div>
        <div class="obmeta"><span class="obcountry">${esc(o.country || 'Multi-location')}</span>${o.date ? ' · ' + esc(o.date) : ''}</div>
        ${o.summary ? `<div class="obsum">${esc(o.summary)}</div>` : ''}
        <div class="obsrc">Official WHO Disease Outbreak News bulletin${o.url ? ` · <a href="${esc(o.url)}" target="_blank" rel="noopener">WHO DON ${esc(o.id || '')} ↗</a>` : ''}</div>
      </div>
    </div>`).join('')
    + `<div class="outbreaknote">${recent.length} WHO Disease Outbreak News bulletins in the last 120 days${archive ? ` · ${archive} older in the WHO archive (not shown)` : ''} · ${O.geocoded || 0} placed on the map. Source: World Health Organization — official outbreak bulletins, not news reports.</div>`;
}

/* ══════════════ 5f. LIVE BROADCASTS (direct HLS from broadcaster CDNs) ══════════════
   No YouTube anywhere: each channel is the broadcaster's OWN public HLS endpoint.
   Every source below was verified reachable cross-origin (Access-Control-Allow-
   Origin present on the master AND the media playlist), so playback happens
   natively in this page — no account, no sign-in wall, no embed restriction.
   Each channel carries fallback sources; if one is unreachable from the viewer's
   network the player advances to the next automatically. */
const LIVE_CHANNELS = [
  { name:'DW English',  region:'Germany',       srcs:['https://dwamdstream102.akamaized.net/hls/live/2015525/dwstream102/index.m3u8'] },
  { name:'Tagesschau',  region:'Germany · ARD', srcs:['https://tagesschau.akamaized.net/hls/live/2020115/tagesschau/tagesschau_1/master.m3u8'] },
  { name:'Al Arabiya',  region:'UAE',           srcs:['https://live.alarabiya.net/alarabiapublish/alarabiya.smil/playlist.m3u8'] },
  { name:'WION',        region:'India',         srcs:['https://d7x8z4yuq42qn.cloudfront.net/index_7.m3u8'] },
  { name:'NDTV 24x7',   region:'India',         srcs:['https://ndtv24x7elemarchana.akamaized.net/hls/live/2003678/ndtv24x7/master.m3u8'] },
  { name:'CNA',         region:'Singapore',     srcs:['https://d2e1asnsl7br7b.cloudfront.net/7782e205e72f43aeb4a48ec97f66ebbe/index.m3u8',
                                                      'https://d2e1asnsl7br7b.cloudfront.net/7782e205e72f43aeb4a48ec97f66ebbe/index_5.m3u8'] },
  { name:'Arirang TV',  region:'South Korea',   srcs:['https://amdlive-ch01-ctnd-com.akamaized.net/arirang_1ch/smil:arirang_1ch.smil/playlist.m3u8'] },
  { name:'Reuters',     region:'Global',        srcs:['https://amg00453-reuters-amg00453c1-rakuten-uk-2110.playouts.now.amagi.tv/playlist/amg00453-reuters-reuters-rakutenuk/playlist.m3u8'] },
  { name:'VOA Africa',  region:'US · Africa',   srcs:['https://voa-ingest.akamaized.net/hls/live/2033874/tvmc06/playlist.m3u8'] },
  { name:'DW Arabic',   region:'Germany',       srcs:['https://dwamdstream104.akamaized.net/hls/live/2015530/dwstream104/index.m3u8'] },
];
let _liveCur = null, _liveHls = null;

function liveMessage(msg, bad){
  const box = $('#livePlayer'); if(!box) return;
  box.innerHTML = `<div class="livemsg mono${bad ? ' bad' : ''}">${esc(msg)}</div>`;
}
function playLiveSource(i){
  const ch = LIVE_CHANNELS.find(c => c.name === _liveCur); if(!ch) return;
  if(i >= ch.srcs.length){
    liveMessage('All sources for ' + ch.name + ' are unreachable from your network right now — try another channel.', true);
    return;
  }
  const box = $('#livePlayer'); if(!box) return;
  if(_liveHls){ try{ _liveHls.destroy(); }catch(e){} _liveHls = null; }
  if(i === 0){
    box.innerHTML = '<video class="livevideo" playsinline muted autoplay controls referrerpolicy="no-referrer"></video>' +
                    '<div class="livebadge">● LIVE</div>';
  }
  const v = box.querySelector('video'); if(!v) return;
  const url = ch.srcs[i];
  const advance = () => playLiveSource(i + 1);
  if(window.Hls && Hls.isSupported()){
    const hls = new Hls({ lowLatencyMode:true, enableWorker:true,
      manifestLoadingTimeOut:12000, manifestLoadingMaxRetry:1, fragLoadingMaxRetry:2 });
    _liveHls = hls;
    hls.loadSource(url);
    hls.attachMedia(v);
    hls.on(Hls.Events.MANIFEST_PARSED, () => { v.play().catch(()=>{}); });
    hls.on(Hls.Events.ERROR, (e, data) => { if(data && data.fatal) advance(); });
  }else if(v.canPlayType('application/vnd.apple.mpegurl')){
    v.src = url;                              // Safari / iOS native HLS
    v.addEventListener('error', advance, { once:true });
    v.play().catch(()=>{});
  }else{
    liveMessage('This browser cannot play HLS streams.', true);
  }
}
function setLiveChannel(name){
  _liveCur = name;
  document.querySelectorAll('#liveChips .lchip').forEach(b => b.classList.toggle('is-on', b.dataset.ch === name));
  playLiveSource(0);
}
function initLive(){
  const box = $('#liveChips'); if(!box) return;
  box.innerHTML = LIVE_CHANNELS.map((c, i) =>
    `<button class="lchip${i === 0 ? ' is-on' : ''}" type="button" data-ch="${esc(c.name)}" title="${esc(c.region)}"><span class="ldot"></span>${esc(c.name)}</button>`).join('');
  const cnt = $('#liveCount');
  if(cnt) cnt.textContent = LIVE_CHANNELS.length + ' channels' + (window.Hls ? '' : ' · native');
  box.querySelectorAll('.lchip').forEach(b => b.addEventListener('click', () => setLiveChannel(b.dataset.ch)));
  // start the first channel only once the card is actually on screen
  const card = document.querySelector('.card.live');
  if(!card || !('IntersectionObserver' in window)){ setLiveChannel(LIVE_CHANNELS[0].name); return; }
  const io = new IntersectionObserver(ents => {
    ents.forEach(e => {
      if(e.isIntersecting && !_liveCur){ setLiveChannel(LIVE_CHANNELS[0].name); io.disconnect(); }
    });
  }, { rootMargin:'250px' });
  io.observe(card);
}

/* ══════════════ 5d. GLOBAL READINESS (DEFCON-style, derived from live data) ══════════════ */
// Honest framing: the US does not publish DEFCON in real time. This is an
// independent, transparent composite of live open data, clearly labelled as
// derived — never presented as an official government readiness level.
function renderDefcon(){
  const body = $('#defconbody'); if(!body) return;
  const F = window.FLOODS || {}, Q = window.QUAKES || {}, OB = window.OUTBREAKS || {};
  const now = Date.now(), wk = 7 * 24 * 3600e3;
  // Each sub-index is normalised to 0..1 so one busy feed (e.g. a quiet-season
  // quake count) cannot saturate the gauge on its own. Weighted, then scaled.
  const fRed = F.red || 0, fOrg = F.orange || 0;
  const floodIdx = Math.min(1, fRed / 20 + fOrg / 60);

  const qs = (Q.quakes || []).filter(q => (q.ts || 0) >= now - wk);
  const maxQ = qs.reduce((m, q) => Math.max(m, q.mag || 0), 0);
  const big = qs.filter(q => (q.mag || 0) >= 5.5).length;
  const quakeIdx = Math.min(1, Math.max(0, (maxQ - 5.0)) / 3.5 + Math.min(0.3, big / 40));

  const recentOb = (OB.items || []).filter(o => {
    const t = Date.parse(o.date || '');
    return !isNaN(t) && (now - t) <= 90 * 24 * 3600e3;
  });
  const obCountries = new Set(recentOb.map(o => o.country).filter(Boolean)).size;
  const obIdx = Math.min(1, Math.min(0.5, recentOb.length / 30) + Math.min(0.3, obCountries / 20));

  let high = 0;
  (S.news || []).forEach(n => {
    const t = ((n.title || '') + ' ' + (n.region || '')).toLowerCase();
    if(/cyber|hack|breach|ransom|war|milit|conflict|attack|strike|invasion|crash|plunge|rout/.test(t)) high++;
  });
  const newsIdx = Math.min(0.25, high / 80);

  const score = Math.round(100 * (0.28 * floodIdx + 0.28 * quakeIdx + 0.24 * obIdx + 0.20 * newsIdx));
  const lvl = score < 18 ? 5 : (score < 36 ? 4 : (score < 58 ? 3 : (score < 78 ? 2 : 1)));
  const LAB = {5:'Normal readiness',4:'Increased watch',3:'Elevated',2:'High',1:'Maximum'};
  const COL = {5:'#22c55e',4:'#38bdf8',3:'#f59e0b',2:'#f97316',1:'#ef4444'};
  const col = COL[lvl];
  const pctOf = v => Math.round(v * 100) + '%';
  const sEl = $('#defconSrc'); if(sEl) sEl.textContent = 'DERIVED · ' + String(F._updated || '').slice(11, 16) + ' UTC';
  body.innerHTML = `
    <div class="dcwrap">
      <div class="dcnum" style="color:${col}">${lvl}<small>DEFCON</small></div>
      <div class="dcinfo">
        <div class="dclab" style="color:${col}">${LAB[lvl]}</div>
        <div class="dcbar"><i style="width:${score}%;background:${col}"></i></div>
        <div class="dcscore">composite threat index <b>${score}</b>/100</div>
      </div>
    </div>
    <div class="dcfac">
      <div class="dcrow"><span>Flood alerting</span><b>${fRed} red · ${fOrg} orange</b><i>${pctOf(floodIdx)}</i></div>
      <div class="dcrow"><span>Seismic (7d)</span><b>${big} at M5.5+ · max M${maxQ.toFixed(1)}</b><i>${pctOf(quakeIdx)}</i></div>
      <div class="dcrow"><span>Outbreaks (WHO, 90d)</span><b>${recentOb.length} bulletins · ${obCountries} countries</b><i>${pctOf(obIdx)}</i></div>
      <div class="dcrow"><span>High-severity headlines</span><b>${high}</b><i>${pctOf(newsIdx)}</i></div>
    </div>
    <div class="dcnote">Derived composite of live open data — flood, seismic, outbreak and headline severity, each normalised then weighted (28/28/24/20). The official US DEFCON is <b>not publicly published</b>; this is an independent indicator, not a government alert level.</div>`;
}

/* ══════════════ 6. AI SITUATION BRIEF (synthesis, labelled) ══════════════ */
function renderBrief(){
  const c=S.coins; const coins=c.length? c:[];
  const btc = coins.find(x=>x.id==='bitcoin');
  const eth = coins.find(x=>x.id==='ethereum');
  const adv = c.filter(x=>(x.price_change_percentage_24h||0)>0).length;
  const topNews = S.news.slice(0,3).map(n=>n.title).filter(Boolean);
  const mktLine = coins.length? `Markets are <b>${adv>coins.length/2?'risk-on':'risk-off'}</b>: ${adv}/${coins.length} watchlist assets up over 24h. BTC trades <b>$${mono(btc?btc.current_price:0)}</b> (${pct(btc?btc.price_change_percentage_24h:0)} 24h), ETH <b>$${mono(eth?eth.current_price:0)}</b>.`
    : 'Markets feed offline — no live synthesis available.';
  const newsLine = topNews.length? 'Headline signals this cycle: '+topNews.map((t,i)=>`<b>${i+1}</b>) ${esc(t)}`).join(' ') + '.' : 'No live headlines — news feed unreachable.';
  $('#briefSrc').textContent = 'SYNTHESIS · ' + (coins.length&&S.news.length?'LIVE':'PARTIAL');
  $('#briefBody').innerHTML = `
    <h3>Market posture</h3>
    <p style="margin:4px 0 0">${mktLine}</p>
    <h3>Intel roundup</h3>
    <p style="margin:4px 0 0">${newsLine}</p>
    <h3>Composition</h3>
    <div class="kv"><span class="k">Coverage</span><span>${coins.length} live assets · ${S.news.length} headlines · ${ZONES.length} time zones</span></div>
    <div class="kv"><span class="k">Method</span><span>Heuristic synthesis of live price + public news RSS</span></div>
    <div class="brief-note">AI-generated summary from live data. Illustrative — verify critical items at the source.</div>`;
}

/* ══════════════ 7. WORLD VIEW ══════════════ */
function renderWorld(){
  // Status board derived from alert keywords on live news (best effort)
  const t = (S.news.map(n=>(n.title||'')).join(' ')+' '+(S.news.map(n=>n.region).join(' '))).toLowerCase();
  const chk=(rx)=>new RegExp(rx).test(t);
  const rows=[
    ['Geopolitical', chk('war|invasion|conflict|milit')?'a':'g', chk('war|invasion')?'Elevated regional tension in coverage':'No conflict alerts in current feed'],
    ['Markets', chk('crash|plunge|rout|record high|surge')?'a':'g', advRatio()],
    ['Cyber', chk('cyber|hack|breach|ransom')?'r':'g', chk('cyber|hack|breach')?'Active breach/ransom reporting':'No cyber incident in current feed'],
    ['Trade / Macro', chk('sanction|tariff|trade war|inflation|rate')?'a':'g', chk('sanction|tariff|trade war')?'Trade action coverage present':'Quiet in current feed'],
    ['Energy', chk('oil|energy|gas|supply')?'a':'g', chk('oil|energy')?'Energy/commodity coverage present':'Quiet in current feed'],
  ];
  $('#statusboard').innerHTML = rows.map(r=>{
    const st = r[1]==='g'?'NOMINAL':(r[1]==='a'?'ELEVATED':'ALERT');
    return `<div class="srowline"><span class="led ${r[1]}"></span><span class="k">${r[0]}</span><span class="v">${r[2]}</span><span class="tag" style="color:${r[1]==='g'?'var(--green)':r[1]==='a'?'var(--amber)':'var(--red)'}">${st}</span></div>`;
  }).join('');
  // cyber grid (best-effort from feed + nominal baseline)
  const cyber=[
    ['Global DNS','NOMINAL','g','monitored'],['Web transport','NOMINAL','g','latency nominal'],
    ['Email / comms','NOMINAL','g','filtered'],['Network ops','NOMINAL','g','no incident'],
    ['Critical infra','WATCH','a', chk('energy|grid')?'energy coverage up':'no outage reported'],
    ['Zero-days','WATCH','a', chk('zero-day|exploit')?'exploit coverage':'no public exploit'],
  ];
  $('#cybergrid').innerHTML = cyber.map(x=>`
    <div class="cyb"><div class="cn"><span>${x[0]}</span><span style="color:${x[2]==='g'?'var(--green)':x[2]==='a'?'var(--amber)':'var(--red)'};font-size:10px">${x[1]}</span></div>
    <div class="cst" style="color:${x[2]==='g'?'var(--text)':'var(--amber)'}">${x[1]}</div><div class="cmeta">${x[3]}</div></div>`).join('');
  // Region pulse (derived keyword heat) — only show regions with live signal.
  const regions=[
    ['Americas', ['america','washington','canada','brazil','us ','mexico']],
    ['Europe', ['europe','germany','france','uk','ukraine','russia','eu ','nato','brussels']],
    ['Middle East', ['iran','israel','gaza','saudi','qatar','iraq','syria','lebanon','middle east']],
    ['Asia-Pacific', ['china','japan','korea','taiwan','india','indonesia','australia','asia']],
    ['Africa', ['africa','niger','sudan','nigeria','kenya','ethiopia','sahel']],
    ['Global Markets', ['market','stock','fed','oil','inflation','dollar','bond','crypto']],
  ];
  const activeRegions = regions
    .map(([name,kws])=>({
      name, kws,
      hits: S.news.filter(n=>kws.some(k=>(n.title||'').toLowerCase().includes(k))).length
    }))
    .filter(r=>r.hits>0);
  $('#regionrow').innerHTML = activeRegions.length
    ? activeRegions.map(({name,kws,hits})=>{
        const sev = hits<=2?'warn':'crit';
        const tags = S.news.filter(n=>kws.some(k=>(n.title||'').toLowerCase().includes(k))).slice(0,3)
          .map(n=>`<span class="tag region">${esc(n.region||'')}</span>`).join('');
        return `<div class="region ${sev}"><div class="rn"><span class="dot"></span>${name}</div>
      <div class="rtemp">${hits}<small> signals</small></div>
      <div class="rl">${hits} matching headline(s) in the live feed this cycle.</div>
      <div class="rtags">${tags}</div></div>`;
      }).join('')
    : '<div class="ph mono" style="grid-column:1/-1;padding:14px">No regional signal in the current feed cycle.</div>';
  updateMapSignals();
}
function advRatio(){
  const c=S.coins; if(!c.length) return '—';
  const adv=c.filter(x=>(x.price_change_percentage_24h||0)>0).length;
  return `${adv}/${c.length} watchlist assets higher on the day`;
}

/* ══════════════ 7b. LIVE WORLD SIGNAL MAP ══════════════ */
// representative hubs; each matches live headlines by keyword
const HUBS=[
  ['United States',38.9,-77.0,['us','u.s.','united states','washington','white house','pentagon','america']],
  ['Canada',45.4,-75.7,['canada','ottawa']],
  ['Mexico',19.4,-99.1,['mexico']],
  ['Brazil',-15.8,-47.9,['brazil']],
  ['Argentina',-34.6,-58.4,['argentina','milei']],
  ['United Kingdom',51.5,-0.1,['uk ','britain','london','westminster','starmer']],
  ['France',48.9,2.35,['france','paris','macron']],
  ['Germany',52.5,13.4,['germany','berlin','scholz']],
  ['European Union',50.85,4.35,['eu ','european union','brussels']],
  ['Russia',55.75,37.6,['russia','moscow','putin']],
  ['Ukraine',50.45,30.5,['ukraine','kyiv']],
  ['Turkey',41.0,28.9,['turkey','erdogan','istanbul']],
  ['Iran',35.7,51.4,['iran','tehran']],
  ['Israel',32.08,34.78,['israel','netanyahu','gaza']],
  ['Saudi Arabia',24.7,46.7,['saudi','riyadh']],
  ['United Arab Emirates',25.2,55.3,['uae','dubai','abu dhabi']],
  ['India',28.6,77.2,['india','delhi','modi']],
  ['China',39.9,116.4,['china','beijing','xi jinping','taiwan','chinese']],
  ['Japan',35.7,139.7,['japan','tokyo']],
  ['South Korea',37.57,126.98,['south korea','seoul','korea']],
  ['Taiwan',25.03,121.57,['taiwan']],
  ['Australia',-33.9,151.2,['australia','sydney','canberra']],
  ['Egypt',30.0,31.2,['egypt','cairo']],
  ['Nigeria',6.5,3.4,['nigeria','lagos']],
  ['Kenya',-1.3,36.8,['kenya','nairobi']],
  ['South Africa',-26.2,28.0,['south africa','johannesburg']],
];
// CARTO dark basemap, split into two layers: the base gets the theme's darkening
// filter, the labels ride in their own pane so place names keep full contrast.
// Filtering a single combined layer measured 5.4:1 -> 2.6:1 on map labels, which
// is a real legibility loss on a map; two layers cost one extra request each.
const TILE_KEY = 'key=cb1_2yip_1_fd870b7c1b2d39e0d7589096';
const TILE_BASE = 'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png?' + TILE_KEY;
const TILE_LABELS = 'https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png?' + TILE_KEY;
const TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>';
let _map=null, _mapMarkers=[];
function hubRe(kws){ return new RegExp('\\b('+kws.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')\\b'); }
function ensureMap(){
  if(_map || typeof L==='undefined') return _map;
  const el=$('#worldmap'); if(!el) return null;
  _map = L.map('worldmap',{ zoomControl:true, worldCopyJump:true, minZoom:2, maxZoom:8 });
  _map.createPane('labelsPane');
  const lp = _map.getPane('labelsPane');
  lp.style.zIndex = 350;          // above the tile pane (200), below overlays (400)
  lp.style.pointerEvents = 'none';
  L.tileLayer(TILE_BASE, { attribution:TILE_ATTR, subdomains:'abcd', maxZoom:8 }).addTo(_map);
  L.tileLayer(TILE_LABELS, { subdomains:'abcd', maxZoom:8, pane:'labelsPane' }).addTo(_map);
  _map.setView([24,10],2);
  return _map;
}
function updateMapSignals(){
  const map=ensureMap(); if(!map) return;
  const titles=(S.news||[]).map(n=>(n.title||'').toLowerCase());
  _mapMarkers.forEach(m=>m.remove()); _mapMarkers=[];
  let liveCount=0;
  HUBS.forEach(([name,lat,lng,kws])=>{
    const re=hubRe(kws);
    const idx=titles.map((t,i)=>({i,t})).filter(o=>re.test(o.t));
    const count=idx.length;
    // Only draw a dot where the live feed actually has signal for that hub.
    // A quiet hub with no matching headlines is just noise — nothing to show.
    if(count>0){
      liveCount++;
      const color = count<=2?'#22c55e':(count<=4?'#f59e0b':'#ef4444');
      const radius = 6 + Math.min(count,7)*2.3;
      const top = S.news[idx[0].i];
      const m = L.circleMarker([lat,lng],{
        radius, color:'#ffffff', weight:1,
        fillColor:color, fillOpacity:0.85
      }).addTo(map);
      m.bindPopup(`<div class="mp-title">${esc(name)}</div>`+
        `<div class="mp-meta">${count} matching headline${count===1?'':'s'} in live feed</div>`+
        `<div style="margin-top:5px">${esc(top.title)}</div>`+
        `<div class="mp-meta" style="margin-top:2px"><a href="${esc(top.link)}" target="_blank" rel="noopener">open story ↗</a></div>`);
      _mapMarkers.push(m);
    }
  });
  // NCMEC missing-child (AMBER) icons on the map — drawn on top of the signal hubs.
  const A = (SET.amber && window.AMBER && Array.isArray(window.AMBER.cases)) ? window.AMBER : null;
  let amberOnMap = 0;
  if(A && typeof L !== 'undefined'){
    const amberIcon = L.divIcon({ className:'amber-marker', html:'<span class="amber-pin">◉</span>', iconSize:[22,22], iconAnchor:[11,11], popupAnchor:[0,-12] });
    A.cases.forEach(c=>{
      if(typeof c.lat==='number' && typeof c.lng==='number'){
        amberOnMap++;
        const m = L.marker([c.lat,c.lng],{ icon:amberIcon }).addTo(map);
        const ageTxt = c.age!=null ? 'Age now: <b>'+c.age+'</b>' : 'Age unknown';
        const missTxt = c.missing ? 'Missing since <b>'+esc(c.missing)+'</b>' : 'Missing';
        m.bindPopup(
          `<div class="mp-title" style="color:#f59e0b">◉ Missing-Child Alert</div>`+
          `<div style="margin:4px 0 2px"><b>${esc(c.name)}</b></div>`+
          `<div class="mp-meta">${ageTxt} · ${missTxt}</div>`+
          `<div class="mp-meta">${esc(c.loc||c.city||'Location undisclosed')}</div>`+
          (c.link?`<div style="margin-top:6px"><a href="${esc(c.link)}" target="_blank" rel="noopener">NCMEC case poster ↗</a></div>`:'')+
          `<div class="mp-meta" style="margin-top:4px;font-size:10px">Report tips to law enforcement / NCMEC 1-800-THE-LOST</div>`);
        _mapMarkers.push(m);
      }
    });
  }
  // ── Seismic (USGS) ────────────────────────────────────────────────────────
  // Real measured events, drawn as dashed rings so they never read as a news
  // signal hub. Size = magnitude, colour = magnitude band, opacity = age.
  const Q = (SET.quakes && window.QUAKES && Array.isArray(window.QUAKES.quakes)) ? window.QUAKES : null;
  let quakeOnMap = 0, quakeMax = 0;
  if(Q && typeof L !== 'undefined'){
    const week = Date.now() - 7*24*60*60*1000;
    const band = q => q.mag >= 5.5 ? '#ef4444' : (q.mag >= 4.2 ? '#f59e0b' : '#38bdf8');
    Q.quakes.slice()
      .filter(q => typeof q.lat==='number' && typeof q.lng==='number' && (q.ts||0)>=week)
      .sort((a,b)=>a.mag-b.mag)          // draw strong events last => on top
      .forEach(q=>{
        quakeOnMap++;
        if(q.mag > quakeMax) quakeMax = q.mag;
        const ageH = (Date.now()-(q.ts||0))/3600000;
        const m = L.circleMarker([q.lat,q.lng],{
          radius: Math.min(4 + (q.mag-2.5)*2.6, 18),
          color: band(q), weight: 1.6, dashArray: '3,3',
          fillColor: band(q), fillOpacity: ageH<=6?0.42:(ageH<=24?0.3:0.18)
        }).addTo(map);
        const utc = new Date(q.ts).toISOString().replace('T',' ').slice(0,16)+' UTC';
        m.bindPopup(
          `<div class="mp-title" style="color:${band(q)}">M${q.mag} earthquake</div>`+
          `<div style="margin:3px 0 2px">${esc(q.place)}</div>`+
          `<div class="mp-meta">Depth <b>${q.depth!=null?q.depth+' km':'unknown'}</b> · ${esc(utc)}</div>`+
          `<div class="mp-meta">${agoLabel(q.ts, Date.now())} ago · USGS event ${esc(q.id||'')}</div>`+
          (q.tsunami?`<div class="mp-meta" style="color:#ef4444;font-weight:600">⚠ TSUNAMI FLAG SET BY USGS</div>`:'')+
          (q.alert?`<div class="mp-meta">USGS impact alert: ${esc(q.alert).toUpperCase()}</div>`:'')+
          (q.url?`<div style="margin-top:6px"><a href="${esc(q.url)}" target="_blank" rel="noopener">USGS event page ↗</a></div>`:''));
        _mapMarkers.push(m);
      });
  }
  // ── Flood alerts (GDACS global + NOAA/NWS US) ─────────────────────────────
  // Drawn as level-coloured triangles so they never read as a news signal hub.
  const FD = (SET.floods && window.FLOODS && Array.isArray(window.FLOODS.events)) ? window.FLOODS : null;
  let floodOnMap = 0, floodRed = 0;
  if(FD && typeof L !== 'undefined'){
    const fcol = l => l === 'Red' ? '#ef4444' : (l === 'Orange' ? '#f59e0b' : '#2dd4bf');
    FD.events.forEach(e=>{
      if(typeof e.lat !== 'number' || typeof e.lng !== 'number') return;
      floodOnMap++;
      if(e.level === 'Red') floodRed++;
      const col = fcol(e.level);
      const ic = L.divIcon({ className:'flood-marker',
        html:'<span class="flood-pin" style="color:'+col+'">▲</span>',
        iconSize:[18,18], iconAnchor:[9,9], popupAnchor:[0,-11] });
      const m = L.marker([e.lat,e.lng],{ icon:ic }).addTo(map);
      m.bindPopup(
        `<div class="mp-title" style="color:${col}">${esc(e.level)} flood alert</div>`+
        `<div style="margin:3px 0 2px">${esc(e.name)}</div>`+
        `<div class="mp-meta">${esc(e.country||'Location undisclosed')}${e.from?` · ${esc(e.from)}${e.to?' → '+esc(e.to):''}`:''}</div>`+
        `<div class="mp-meta">Source: GDACS global flood alerting</div>`+
        (e.report?`<div style="margin-top:6px"><a href="${esc(e.report)}" target="_blank" rel="noopener">GDACS report ↗</a></div>`:''));
      _mapMarkers.push(m);
    });
  }
  // ── Outbreak reports (WHO Disease Outbreak News) ──────────────────────────
  const OB = (SET.outbreaks && window.OUTBREAKS && Array.isArray(window.OUTBREAKS.items)) ? window.OUTBREAKS : null;
  let outbreakOnMap = 0;
  if(OB && typeof L !== 'undefined'){
    const obIcon = L.divIcon({ className:'outbreak-marker',
      html:'<span class="outbreak-pin">☣</span>', iconSize:[18,18], iconAnchor:[9,9], popupAnchor:[0,-11] });
    OB.items.forEach(o=>{
      if(typeof o.lat !== 'number' || typeof o.lng !== 'number') return;
      outbreakOnMap++;
      const m = L.marker([o.lat, o.lng],{ icon:obIcon }).addTo(map);
      m.bindPopup(
        `<div class="mp-title" style="color:#8b8bff">☣ Outbreak report</div>`+
        `<div style="margin:3px 0 2px"><b>${esc(o.disease||o.title||'')}</b></div>`+
        `<div class="mp-meta">${esc(o.country||'Multi-location')}${o.date?' · '+esc(o.date):''}</div>`+
        (o.summary?`<div class="mp-meta" style="margin-top:4px">${esc(o.summary.slice(0,180))}…</div>`:'')+
        `<div class="mp-meta" style="margin-top:4px">Source: WHO Disease Outbreak News</div>`+
        (o.url?`<div style="margin-top:6px"><a href="${esc(o.url)}" target="_blank" rel="noopener">WHO bulletin ↗</a></div>`:''));
      _mapMarkers.push(m);
    });
  }
  // Legend is assembled from whichever layers are actually switched on (Settings).
  const leg = [
    `<span class="li"><span class="sw" style="background:#22c55e"></span>active</span>`,
    `<span class="li"><span class="sw" style="background:#f59e0b"></span>heightened</span>`,
    `<span class="li"><span class="sw" style="background:#ef4444"></span>elevated</span>`,
  ];
  if(SET.quakes){
    leg.push(`<span class="li"><span class="sw quake-sw qk-minor"></span>M2.5–4.2 quake</span>`,
             `<span class="li"><span class="sw quake-sw qk-mid"></span>M4.2–5.5 quake</span>`,
             `<span class="li"><span class="sw quake-sw qk-major"></span>M5.5+ quake · USGS</span>`);
  }
  if(SET.amber){
    leg.push(`<span class="li"><span class="sw amber-dot"></span>◉ NCMEC missing-child alert</span>`);
  }
  if(SET.floods){
    leg.push(`<span class="li"><span class="sw flood-sw lv-red"></span>Red flood</span>`,
             `<span class="li"><span class="sw flood-sw lv-orange"></span>Orange flood</span>`,
             `<span class="li"><span class="sw flood-sw lv-green"></span>Green flood · GDACS</span>`);
  }
  if(SET.outbreaks){
    leg.push(`<span class="li"><span class="sw ob-sw"></span>☣ WHO outbreak report</span>`);
  }
  $('#mapLegend').innerHTML = leg.join('');
  const qtxt = !SET.quakes ? ''
    : (quakeOnMap
        ? ' · '+quakeOnMap+' quake'+(quakeOnMap===1?'':'s')+(quakeMax?' (max M'+quakeMax+')':'')
        : (Q ? ' · no quakes in window' : ''));
  const ftxt = !SET.floods ? ''
    : (floodOnMap
        ? ' · '+floodOnMap+' flood'+(floodOnMap===1?'':'s')+(floodRed?' ('+floodRed+' red)':'')
        : (FD ? ' · no flood alerts' : ''));
  const otxt = !SET.outbreaks ? ''
    : (outbreakOnMap ? ' · '+outbreakOnMap+' outbreak'+(outbreakOnMap===1?'':'s')
        : (OB ? ' · no outbreak reports' : ''));
  $('#mapCount').textContent =
    (liveCount ? liveCount+' signal'+(liveCount===1?'':'s')+' live' : 'no regional activity this cycle') + qtxt + ftxt + otxt;
  const amc = $('#amberMapCount'); if(amc && amberOnMap) amc.textContent = amberOnMap+' on map';
}
function wakeMap(){
  if(SET.mapMode === '3d'){ setMapMode('3d'); return; }
  ensureMap(); if(_map){ _map.invalidateSize(); } updateMapSignals();
}

/* ══════════════ 7c. 3D GLOBE (canvas orthographic, auto-rotating) ══════════════
   A real globe (not a flat map): orthographic projection on a 2D canvas, so it
   needs no WebGL and renders everywhere. Same live layers as the 2D map —
   news signal hubs, USGS quakes, GDACS/NWS floods and NCMEC amber cases.
   Geometry comes from Natural Earth (world-atlas, via CDN like Leaflet). */
const GLOBE_CDN = {
  d3:    'https://unpkg.com/d3@7/dist/d3.min.js',
  topo:  'https://unpkg.com/topojson-client@3/dist/topojson-client.min.js',
  land:  'https://unpkg.com/world-atlas@2/land-110m.json',
};
let _globe = null;
function loadScript(src){
  return new Promise((res, rej)=>{
    const s = document.createElement('script');
    s.src = src; s.onload = res; s.onerror = () => rej(new Error('load ' + src));
    document.head.appendChild(s);
  });
}
async function ensureGlobe(){
  if(_globe && _globe.ready) return _globe;
  const canvas = $('#globecanvas'); if(!canvas) return null;
  try{
    if(typeof d3 === 'undefined') await loadScript(GLOBE_CDN.d3);
    if(typeof topojson === 'undefined') await loadScript(GLOBE_CDN.topo);
    if(!window.__wmLand){
      const r = await fetch(GLOBE_CDN.land); if(!r.ok) throw new Error('land ' + r.status);
      const topo = await r.json();
      window.__wmLand = topojson.feature(topo, topo.objects.land);
    }
    _globe = { canvas, ctx: canvas.getContext('2d'), land: window.__wmLand,
               rot:[12,-16,0], auto:true, ready:true, raf:null, drag:false, w:0, h:0, hits:[] };
    sizeGlobe();
    bindGlobeDrag();
    startGlobe();
    const fb = $('#globefallback');
    if(fb) fb.textContent = 'Drag the globe to spin · tap a marker for details · Natural Earth 110m';
    return _globe;
  }catch(e){
    const fb = $('#globefallback');
    if(fb) fb.textContent = '3D globe unavailable offline — showing the 2D map.';
    setMapMode('2d');
    return null;
  }
}
function sizeGlobe(){
  const g = _globe; if(!g) return;
  const box = $('#globebox'); if(!box) return;
  const w = box.clientWidth || 900, h = box.clientHeight || 430;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  g.canvas.width = Math.round(w * dpr); g.canvas.height = Math.round(h * dpr);
  g.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.w = w; g.h = h;
  g.proj = d3.geoOrthographic().translate([w/2, h/2])
             .scale(Math.min(w, h) * 0.46).rotate(g.rot).clipAngle(90);
  g.path = d3.geoPath(g.proj, g.ctx);
  if(!g.grat) g.grat = d3.geoGraticule10();
}
function plotGlobePt(lng, lat, color, size, kind, data){
  const g = _globe; if(!g) return;
  const c = [-g.rot[0], -g.rot[1]];
  if(d3.geoDistance([lng, lat], c) > Math.PI/2 - 0.02) return;   // far side of the globe
  const p = g.proj([lng, lat]); if(!p) return;
  const ctx = g.ctx; ctx.save();
  if(kind === 'ring'){
    ctx.beginPath(); ctx.arc(p[0], p[1], size, 0, 6.2832);
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
  }else{
    ctx.beginPath();
    if(kind === 'tri'){ ctx.moveTo(p[0], p[1]-size); ctx.lineTo(p[0]+size*0.95, p[1]+size*0.72); ctx.lineTo(p[0]-size*0.95, p[1]+size*0.72); ctx.closePath(); }
    else if(kind === 'dia'){ ctx.moveTo(p[0], p[1]-size); ctx.lineTo(p[0]+size, p[1]); ctx.lineTo(p[0], p[1]+size); ctx.lineTo(p[0]-size, p[1]); ctx.closePath(); }
    else { ctx.arc(p[0], p[1], size, 0, 6.2832); }
    ctx.fillStyle = color; ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.55)'; ctx.lineWidth = 0.8; ctx.stroke();
  }
  ctx.restore();
  // Canvas has no DOM nodes, so remember where each marker landed this frame.
  // globeTapTest() hit-tests against this list — without it the dots are unclickable.
  if(data) g.hits.push({ x:p[0], y:p[1], r:size, data });
}
function drawGlobe(){
  const g = _globe; if(!g || !g.proj) return;
  const { ctx, w, h } = g;
  ctx.clearRect(0, 0, w, h);
  ctx.beginPath(); g.path({type:'Sphere'});
  ctx.fillStyle = '#0a1220'; ctx.fill();
  ctx.beginPath(); g.path(g.grat);
  ctx.strokeStyle = 'rgba(110,168,254,.10)'; ctx.lineWidth = 1; ctx.stroke();
  ctx.beginPath(); g.path(g.land);
  ctx.fillStyle = '#182338'; ctx.fill();
  ctx.strokeStyle = '#2b3a58'; ctx.lineWidth = 0.7; ctx.stroke();
  ctx.beginPath(); g.path({type:'Sphere'});
  ctx.strokeStyle = 'rgba(110,168,254,.35)'; ctx.lineWidth = 1.2; ctx.stroke();

  g.hits = [];                        // rebuilt every frame; hit-testing reads this

  // news signal hubs (same keyword matching the 2D map uses)
  if(S.news && S.news.length){
    const titles = S.news.map(n => (n.title || '').toLowerCase());
    HUBS.forEach(([name, lat, lng, kws])=>{
      const re = hubRe(kws);
      const idx = [];
      titles.forEach((t, i) => { if(re.test(t)) idx.push(i); });
      const count = idx.length;
      if(count > 0){
        const col = count <= 2 ? '#22c55e' : (count <= 4 ? '#f59e0b' : '#ef4444');
        const top = S.news[idx[0]];
        plotGlobePt(lng, lat, col, Math.min(3 + count * 1.1, 10), 'circle', {
          color: col, title: name,
          lines: [count + ' matching headline' + (count === 1 ? '' : 's') + ' in live feed', top ? top.title : ''],
          link: top ? top.link : '', linkText: 'open story ↗'
        });
      }
    });
  }
  if(SET.quakes && window.QUAKES && Array.isArray(window.QUAKES.quakes)){
    const wk = Date.now() - 7*24*3600e3;
    window.QUAKES.quakes.filter(q => (q.ts||0) >= wk).forEach(q=>{
      const col = q.mag >= 5.5 ? '#ef4444' : (q.mag >= 4.2 ? '#f59e0b' : '#38bdf8');
      const utc = new Date(q.ts).toISOString().replace('T',' ').slice(0,16) + ' UTC';
      plotGlobePt(q.lng, q.lat, col, Math.min(3 + (q.mag-2.5)*1.5, 11), 'ring', {
        color: col, title: 'M' + q.mag + ' earthquake',
        lines: [ q.place,
                 'Depth ' + (q.depth != null ? q.depth + ' km' : 'unknown') + ' · ' + utc,
                 agoLabel(q.ts, Date.now()) + ' ago · USGS event ' + (q.id || ''),
                 q.tsunami ? '⚠ TSUNAMI FLAG SET BY USGS' : '',
                 q.alert ? 'USGS impact alert: ' + String(q.alert).toUpperCase() : '' ],
        link: q.url || '', linkText: 'USGS event page ↗'
      });
    });
  }
  if(SET.floods && window.FLOODS && Array.isArray(window.FLOODS.events)){
    window.FLOODS.events.forEach(e=>{
      const col = e.level === 'Red' ? '#ef4444' : (e.level === 'Orange' ? '#f59e0b' : '#2dd4bf');
      plotGlobePt(e.lng, e.lat, col, 5.5, 'tri', {
        color: col, title: e.level + ' flood alert',
        lines: [ e.name,
                 (e.country || 'Location undisclosed') + (e.from ? ' · ' + e.from + (e.to ? ' → ' + e.to : '') : ''),
                 'Source: GDACS global flood alerting' ],
        link: e.report || '', linkText: 'GDACS report ↗'
      });
    });
  }
  if(SET.amber && window.AMBER && Array.isArray(window.AMBER.cases)){
    window.AMBER.cases.forEach(c=>{
      if(typeof c.lat !== 'number') return;
      plotGlobePt(c.lng, c.lat, '#f59e0b', 5, 'dia', {
        color: '#f59e0b', title: '◉ Missing-Child Alert',
        lines: [ c.name,
                 (c.age != null ? 'Age now: ' + c.age : 'Age unknown') + (c.missing ? ' · Missing since ' + c.missing : ''),
                 c.loc || c.city || 'Location undisclosed',
                 'Report tips to law enforcement / NCMEC 1-800-THE-LOST' ],
        link: c.link || '', linkText: 'NCMEC case poster ↗'
      });
    });
  }
  if(SET.outbreaks && window.OUTBREAKS && Array.isArray(window.OUTBREAKS.items)){
    window.OUTBREAKS.items.forEach(o=>{
      if(typeof o.lat !== 'number') return;
      plotGlobePt(o.lng, o.lat, '#8b8bff', 5.5, 'circle', {
        color: '#8b8bff', title: '☣ Outbreak report',
        lines: [ o.disease || o.title || '',
                 (o.country || 'Multi-location') + (o.date ? ' · ' + o.date : ''),
                 o.summary ? o.summary.slice(0, 170) + '…' : '',
                 'Source: WHO Disease Outbreak News' ],
        link: o.url || '', linkText: 'WHO bulletin ↗'
      });
    });
  }
}
function globeFrame(){
  const g = _globe; if(!g || !g.ready) return;
  if(g.auto && !g.drag){
    g.rot[0] += 0.11; if(g.rot[0] > 180) g.rot[0] -= 360;
    g.proj.rotate(g.rot);
  }
  drawGlobe();
  g.raf = requestAnimationFrame(globeFrame);
}
function startGlobe(){
  const g = _globe; if(!g || g.raf) return;
  if(document.body.classList.contains('motion-off')) { drawGlobe(); return; }   // honour reduced-motion setting
  g.raf = requestAnimationFrame(globeFrame);
}
function stopGlobe(){ const g = _globe; if(g && g.raf){ cancelAnimationFrame(g.raf); g.raf = null; } }
/* ── Marker popups on the canvas globe ──────────────────────────────────────
   The globe is a single <canvas>, so markers are pixels with no DOM identity.
   plotGlobePt() records each marker's screen position every frame into g.hits;
   a tap is hit-tested against that list and the details render into a normal
   DOM overlay (#globeTip) so the links inside it are real, clickable anchors. */
function globeTapTest(clientX, clientY){
  const g = _globe; if(!g || !g.hits || !g.hits.length) return null;
  const r = g.canvas.getBoundingClientRect();
  const x = clientX - r.left, y = clientY - r.top;
  // Nearest marker within the tolerance wins, so tapping a specific dot selects
  // that dot rather than a neighbour; the 0.5px slack lets a later-drawn
  // (topmost) marker win an exact tie.
  let best = null, bestD = Infinity;
  for(let i = 0; i < g.hits.length; i++){
    const h = g.hits[i];
    const tol = Math.max(h.r + 8, 14);          // finger-friendly target
    const d = Math.hypot(h.x - x, h.y - y);
    if(d <= tol && d <= bestD + 0.5){ best = h; bestD = d; }
  }
  return best;
}
function hideGlobeTip(){
  const tip = $('#globeTip'); if(tip) tip.hidden = true;
  const g = _globe; if(g && !document.body.classList.contains('motion-off')) g.auto = true;
}
function showGlobeTip(hit){
  const box = $('#globebox'), tip = $('#globeTip');
  if(!box || !tip || !hit) return;
  const d = hit.data || {};
  tip.innerHTML =
    '<button class="gt-close" type="button" aria-label="Close">×</button>' +
    '<div class="gt-title" style="color:' + esc(d.color || '#fff') + '">' + esc(d.title || '') + '</div>' +
    (d.lines || []).filter(Boolean).map(l => '<div class="gt-line">' + esc(l) + '</div>').join('') +
    (d.link ? '<a class="gt-link" href="' + esc(d.link) + '" target="_blank" rel="noopener">' +
              esc(d.linkText || 'open ↗') + '</a>' : '');
  tip.hidden = false;
  const bw = box.clientWidth, bh = box.clientHeight;
  const tw = tip.offsetWidth || 236, th = tip.offsetHeight || 100;
  let x = hit.x + 16, y = hit.y - Math.round(th / 2);
  if(x + tw > bw - 8) x = hit.x - tw - 16;              // flip to the other side
  x = Math.max(8, Math.min(x, Math.max(8, bw - tw - 8)));
  y = Math.max(8, Math.min(y, Math.max(8, bh - th - 8)));
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
  const g = _globe; if(g) g.auto = false;               // hold still while open, else it drifts
  const cl = tip.querySelector('.gt-close');
  if(cl) cl.addEventListener('click', hideGlobeTip);
}
function bindGlobeDrag(){
  const g = _globe; if(!g) return;
  const c = g.canvas; let last = null, tap = null;
  c.addEventListener('pointerdown', e=>{
    g.drag = true; last = {x:e.clientX, y:e.clientY};
    tap = {x:e.clientX, y:e.clientY, t:Date.now(), moved:0};
    g.auto = false;      // freeze on press, else the marker drifts out from under the finger
    try{ c.setPointerCapture(e.pointerId); }catch(_){}
  });
  c.addEventListener('pointermove', e=>{
    if(!g.drag || !last){
      // hover affordance: show a pointer when over a marker
      if(!tap && e.pointerType === 'mouse'){
        c.style.cursor = globeTapTest(e.clientX, e.clientY) ? 'pointer' : 'grab';
      }
      return;
    }
    const dx = e.clientX - last.x, dy = e.clientY - last.y;
    if(tap) tap.moved += Math.abs(dx) + Math.abs(dy);
    if(tap && tap.moved > 7){
      const tip = $('#globeTip');
      if(tip && !tip.hidden) hideGlobeTip();     // a spin detaches it from its marker
    }
    last = {x:e.clientX, y:e.clientY};
    g.rot[0] += dx * 0.28;
    g.rot[1] = Math.max(-80, Math.min(80, g.rot[1] - dy * 0.25));
    g.proj.rotate(g.rot);
    if(g.raf === null) drawGlobe();     // static mode: redraw on drag
  });
  c.addEventListener('pointerup', e=>{
    const wasTap = tap && tap.moved < 7 && (Date.now() - tap.t) < 700;
    g.drag = false; last = null; tap = null;
    if(!wasTap){ hideGlobeTip(); return; }   // a real spin — and it resumes rotation
    const hit = globeTapTest(e.clientX, e.clientY);
    if(hit) showGlobeTip(hit);               // keeps the globe frozen while the card is open
    else hideGlobeTip();                     // empty space: dismiss + resume rotation
  });
  const up = ()=>{
    g.drag = false; last = null; tap = null;
    const tip = $('#globeTip');            // cancelled press: resume spin if no card is open
    if((!tip || tip.hidden) && !document.body.classList.contains('motion-off')) g.auto = true;
  };
  ['pointercancel','pointerleave'].forEach(ev=> c.addEventListener(ev, up));
}
function setMapMode(mode){
  SET.mapMode = (mode === '3d') ? '3d' : '2d'; saveSettings();
  hideGlobeTip();                     // never leave a stale popup behind on a mode swap
  const is3 = SET.mapMode === '3d';
  const two = $('#worldmap'), box = $('#globebox');
  const b2 = $('#map2dBtn'), b3 = $('#map3dBtn');
  if(box) box.hidden = !is3;
  if(two) two.style.display = is3 ? 'none' : '';
  if(b2){ b2.classList.toggle('is-on', !is3); b2.setAttribute('aria-pressed', String(!is3)); }
  if(b3){ b3.classList.toggle('is-on', is3);  b3.setAttribute('aria-pressed', String(is3)); }
  if(is3){
    ensureGlobe().then(g=>{ if(g){ sizeGlobe(); startGlobe(); } });
  }else{
    stopGlobe();
    ensureMap(); if(_map){ setTimeout(()=>_map.invalidateSize(), 60); }
    try{ updateMapSignals(); }catch(_){}
  }
}

/* ══════════════ 8. PROPHECY (News & Prophecy causal analyses) ══════════════ */
function propCoverage(p){
  // how many live headlines currently match this prophecy's cause keywords
  if(!S.news || !p.kw) return 0;
  const rx = new RegExp('\\b('+p.kw.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')\\b','i');
  return S.news.filter(n=>rx.test((n.title||'')+' '+(n.region||''))).length;
}
// render markdown **bold** to <b> after escaping (data is trusted; esc() neutralizes raw HTML)
function fmt(s){ return esc(s).replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>'); }
function renderProphecy(){
  const list = window.PROPHECIES || [];
  if(!list.length){ $('#proplist').innerHTML = `<div class="ph mono" style="padding:20px">Prophecy data not loaded.</div>`; return; }
  const track = list.filter(p=>propCoverage(p)>0).length;
  $('#propCount').textContent = list.length+' prophecies · '+track+' tracked live';
  $('#propSrc').textContent = 'UPDATED '+list._updated;
  $('#proplist').innerHTML = list.map((p,i)=>{
    const cov = propCoverage(p);
    const covCls = cov===0?'quiet':(cov<=2?'active':'hot');
    const covTxt = cov===0 ? 'no live headline yet' : (cov+' headline'+(cov===1?'':'s')+' tracking');
    const tagTone = p.cls==='red'?'var(--tx-red)/var(--bg-red)':(p.cls==='amber'?'var(--tx-amber)/var(--bg-amber)':'var(--tx-blue)/var(--bg-blue)');
    const [tc,tb]=tagTone.split('/');
    const bullets = (p.bullets||[]).map(b=>`<li>${fmt(b)}</li>`).join('');
    return `<details class="prop" ${i===0?'open':''}>
      <summary>
        <span class="pflag">${p.emoji||''}</span>
        <span class="phead">
          <span class="ptitle">${esc(p.short||p.title||'')}</span>
          <span class="pmeta-line">
            <span class="tag ptone" style="color:${tc};background:${tb}">${esc(p.tag||'')}</span>
            <span class="pcov ${covCls}"><i class="dot"></i>${covTxt}</span>
          </span>
        </span>
        <span class="chev">▾</span>
      </summary>
      <div class="pbody">
        <div class="psec cause">
          <div class="psec-h"><span class="badge dang">OBSERVED CAUSE</span><span class="psec-note">what is happening now</span></div>
          <p class="ptext">${fmt(p.cause)}</p>
        </div>
        <div class="psec">
          <div class="psec-h"><span class="badge warn">PROJECTED EFFECT · if cause persists</span></div>
          <ul class="pbullet">${bullets}</ul>
        </div>
        <div class="psec hinge">
          <div class="psec-h"><span class="badge hinge">THE HINGE · the choice that rewrites it</span></div>
          <p class="ptext">${fmt(p.hinge)}</p>
        </div>
      </div>
    </details>`;
  }).join('');
}

/* ══════════════ WELCOME GUIDE ══════════════ */
const GUIDE=[
  {icon:'🛰️',h:'Welcome to World Monitor',p:'Your global intelligence workspace — live markets, geopolitical headlines, world clocks and risk signals synthesized into one screen.'},
  {icon:'📈',h:'Markets',p:'A live watchlist of major crypto assets with real prices, 24h changes and 7-day sparklines — pulled straight from public market data. The top ticker scrolls the full watchlist.'},
  {icon:'🕐',h:'World Clocks',p:'Real-time local time across 16 global cities and UTC — so you always know what hour it is in any major market or capital.'},
  {icon:'📰',h:'Intel Feed',p:'Live headlines from public RSS plus public Telegram, Reddit and X posts — social entries are labelled unverified first reports. Alerts auto-classify high-priority items and lead with measured USGS seismic events.'},
  {icon:'🌊',h:'Floods, Outbreaks & Readiness',p:'The Flood Report lists live flood alerts worldwide from GDACS plus NOAA/NWS US warnings; the Outbreak Report lists official WHO Disease Outbreak News bulletins, both drawn as icons on the map. Beside them, the DEFCON-style readiness indicator is a transparent composite of flood, seismic, outbreak and headline severity — clearly labelled as derived, because the official US DEFCON is not publicly published.'},
  {icon:'🌐',h:'2D map or 3D globe',p:'In the World tab, switch the map between the flat 2D map and a 3D rotating globe. Drag the globe to spin it yourself, or let it auto-rotate. Both views carry the same live layers.'},
  {icon:'📺',h:'Live Broadcasts',p:'The Intel tab plays live news straight from broadcasters’ own public HLS streams — DW English, Tagesschau, Al Arabiya, WION, NDTV 24x7, CNA, Arirang TV, Reuters, VOA Africa and DW Arabic. No YouTube, no sign-in, no embed wall: the stream plays natively in the page, and if a source is unreachable from your network the player falls over to that channel’s next source automatically.'},
  {icon:'🧭',h:'Use it',p:'Switch sections with the tabs (Markets · Intel · Prophecy · Alerts · World · Settings). ⚙ Settings controls the look (HUD effects, motion, density), which sources feed the Intel panel, the map layers, 2D/3D map view, focus regions, clock format and refresh rate — all stored in your browser only. Live data refreshes automatically. Beta — verify critical intelligence independently.'},
];
let guideIdx=0;
function openGuide(){ $('#welcome').hidden=false; renderGuide(); }
function renderGuide(){
  const g=GUIDE[guideIdx];
  $('#guideBody').innerHTML=`<div class="gicon">${g.icon}</div><h3>${g.h}</h3><p>${g.p}</p>`;
  $('#guidePag').textContent=(guideIdx+1)+' / '+GUIDE.length;
  $('#guideDots').innerHTML=GUIDE.map((_,i)=>`<i class="${i===guideIdx?'on':''}"></i>`).join('');
  $('#guideNext').textContent = guideIdx===GUIDE.length-1?'Start':'Next';
}
function nextGuide(){
  if(guideIdx<GUIDE.length-1){guideIdx++;renderGuide();}
  else closeGuide();
}
function closeGuide(){ $('#welcome').hidden=true; }

/* ══════════════ TABS ══════════════ */
function bindTabs(){
  // Scope to the nav strip: the Settings/Help buttons also carry the `tab` class
  // for styling, and binding them here made a click on either one clear the
  // active tab and hide every view (dataset.view is undefined, so the toggle
  // matched nothing) — the dashboard went blank until a real tab was clicked.
  $$('.tabs .tab').forEach(t=>{
    if(!t.dataset.view) return;
    t.addEventListener('click',()=>{
      $$('.tabs .tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')});
      t.classList.add('is-active');t.setAttribute('aria-selected','true');
      const v=t.dataset.view;
      $$('.view').forEach(s=>s.classList.toggle('is-active', s.id==='view-'+v));
      if(v==='world') setTimeout(wakeMap, 60);   // init/resize the map (or globe) once visible
      else { stopGlobe(); hideGlobeTip(); }     // pause globe + drop any popup off-screen
      try{ history.replaceState(null,'','#'+v); }catch(e){}
      window.scrollTo({top:0,behavior:'smooth'});
    });
  });
}

/* ══════════════ BOOT ══════════════ */
function boot(){
  bindTabs();
  bindSettings();
  // honor #view hash first, then the saved default view from Settings
  const want = (location.hash||'').replace('#','') || SET.view;
  if(['markets','intel','prophecy','world','alerts'].includes(want)){
    const t=$(`.tab[data-view=${want}]`);
    if(t){ $$('.tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')});
      t.classList.add('is-active');t.setAttribute('aria-selected','true');
      $$('.view').forEach(s=>s.classList.toggle('is-active', s.id==='view-'+want)); }
    if(want==='world') setTimeout(wakeMap, 80);
  }
  $('#guideNext').addEventListener('click',nextGuide);
  $('#closeGuide').addEventListener('click',closeGuide);
  tickClocks(); setInterval(tickClocks,1000);
  renderAmber();   // NCMEC amber panel renders from committed snapshot — independent of news fetch
  renderFloods();  // GDACS/NWS flood report — committed snapshot, independent of news fetch
  renderOutbreaks(); // WHO Disease Outbreak News report — committed snapshot
  renderDefcon();  // derived readiness indicator — recomputed on each news refresh
  initLive();      // live news broadcast channels (iframe loads when the card is in view)
  loadMarkets(); setInterval(loadMarkets,60000);
  applySettings();   // saved display classes + first feed render + refresh timer
  loadPrediction(); setInterval(loadPrediction,300000);
  loadFX(); setInterval(loadFX,300000);
  renderFiatleak(); setInterval(refreshFiatleak,1800000);   // refresh fiatleak.js hourly data
  // guide on first visit (skip when arriving via a section deep-link)
  if(!location.hash && !localStorage.getItem('wm_seen')){ openGuide(); localStorage.setItem('wm_seen','1'); }
  $('#helpBtn').addEventListener('click',openGuide);
  // 2D map / 3D globe toggle
  const b2 = $('#map2dBtn'), b3 = $('#map3dBtn');
  if(b2) b2.addEventListener('click', ()=>setMapMode('2d'));
  if(b3) b3.addEventListener('click', ()=>setMapMode('3d'));
  window.addEventListener('resize', ()=>{
    const gb = $('#globebox');
    if(SET.mapMode === '3d' && gb && !gb.hidden) sizeGlobe();
  });
  // page visibility keeps data honest on reload/tab-return (and parks the globe)
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden){ stopGlobe(); }
    else { tickClocks(); if(SET.mapMode === '3d') startGlobe(); }
  });
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
else boot();
