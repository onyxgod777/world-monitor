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

const PROXIES = [
  'https://api.allorigins.win/raw?url=',
  'https://api.codetabs.com/v1/proxy?quest=',
  'https://api.corsproxy.io/?url=',
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
  // Fire all proxies in parallel and take the first that succeeds. A slow or dead
  // proxy must never stall the dashboard, so each attempt is short and the whole
  // call resolves in ~4s worst case instead of 3 x 8s sequentially.
  const attempts = PROXIES.map((p,i)=>
    fetchTimeout(p+target, 4200)
      .then(res=>{ if(!res.ok) throw new Error('proxy '+i+' '+res.status); _activeProxy=i; return res; })
  );
  const settled = await Promise.allSettled(attempts);
  const ok = settled.find(r=>r.status==='fulfilled');
  if(ok) return ok.value;
  const bad = settled.find(r=>r.status==='rejected');
  throw (bad? bad.reason : new Error('no proxy'));
}

/* ───────── app state ───────── */
const S = { coins: [], news: [], online: false, lastFetch: 0 };

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
  const opts = { timeZone: zone, hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false };
  const time = new Intl.DateTimeFormat('en-GB', opts).format(now);
  const day = new Intl.DateTimeFormat('en-GB', { timeZone: zone, weekday:'short' }).format(now);
  return { time, day };
}
function tickClocks(){
  const now = new Date();
  $('#utcClock').textContent = new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(now) + ' UTC';
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

async function loadMarkets(){
  const ids = COINS.join(',');
  const url = `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids}&order=market_cap_desc&per_page=50&sparkline=true&price_change_percentage=24h%2C7d`;
  let coins=[];
  try{
    const res = await fetchTimeout(url, 9000);
    if(!res.ok) throw new Error('cg '+res.status);
    coins = await res.json();
  }catch(e){
    // CoinGecko can rate-limit; retry via proxy once
    try{ coins = await (await proxied(url)).json(); }catch(e2){}
  }
  if(!coins || !coins.length){ renderMarketsOffline(); return; }
  S.coins = coins.filter(c=>COIN_NAME[c.id]);
  S.online = true;
  renderMarkets();
  renderEcon();
  renderRisk();
}
function renderMarkets(){
  const coins = S.coins;
  $('#mktSrc').textContent = 'COINGECKO · LIVE';
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
  $('#mktSrc').textContent = 'OFFLINE · SAMPLE';
  setStatus(false,'STATUS: MARKETS OFFLINE');
  const tpl=['BTC','ETH','SOL','XRP'];
  $('#ticker').innerHTML = `<span class="ticker-inner">${tpl.map(s=>`<span class="tk">${s} <span class="flat">— offline —</span></span><span class="sep"></span>`).join('')}${tpl.map(s=>`<span class="tk">${s} <span class="flat">— offline —</span></span><span class="sep"></span>`).join('')}</span>`;
  $('#watchgrid').innerHTML = `<div class="ph mono" style="grid-column:1/-1;padding:20px;text-align:center">Live price feed unreachable — showing sample tiles. Markets panel will recover automatically when the API responds.</div>`;
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
async function loadPrediction(){
  const url='https://gamma-api.polymarket.com/markets?active=true&closed=false&order=volume24hr&ascending=false&limit=15';
  try{
    const res=await fetchTimeout(url,9000);
    if(!res.ok) throw new Error('pm '+res.status);
    const d=await res.json();
    const list=(Array.isArray(d)?d:[]).filter(m=>{
      try{ const o=JSON.parse(m.outcomes||'[]'); return o.length===2 && (parseFloat(m.liquidity)>0); }catch(e){ return false; }
    });
    if(!list.length) throw new Error('empty');
    renderPrediction(list.slice(0,10));
    $('#predCount').textContent=list.length+' markets';
    $('#predSrc').textContent='POLYMARKET · LIVE';
  }catch(e){
    $('#predSrc').textContent='POLYMARKET · OFFLINE';
    $('#predlist').innerHTML=`<div class="ph mono" style="padding:18px">Prediction feed unreachable — retrying automatically. Markets &amp; clocks stay live.</div>`;
  }
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

/* ══════════════ 4. INTEL FEED (news RSS, best-effort) ══════════════ */
const NEWS_FEEDS = [
  { region:'World', src:'Google News', url:'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en' },
  { region:'Markets', src:'Google News', url:'https://news.google.com/rss/search?q=global%20markets%20economy&hl=en-US&gl=US&ceid=US:en' },
  { region:'Cyber', src:'Google News', url:'https://news.google.com/rss/search?q=cybersecurity%20hack%20breach&hl=en-US&gl=US&ceid=US:en' },
  { region:'Geo', src:'Google News', url:'https://news.google.com/rss/search?q=geopolitics%20diplomacy&hl=en-US&gl=US&ceid=US:en' },
  { region:'Energy', src:'Google News', url:'https://news.google.com/rss/search?q=oil%20energy%20commodities&hl=en-US&gl=US&ceid=US:en' },
];
const SAMPLE_ITEMS = [
  {title:'Live feeds unreachable — sample item. Markets &amp; clocks remain live.', when:'now', region:'World', src:'SAMPLE', cat:'flat'},
];
// Outlets that hard-paywall their articles. Drop their items so every feed & alert
// link opens a source you can actually read. Matched word-boundary against the
// outlet name Google News attaches to each item.
const PAYWALLED = [
  'new york times','nytimes','nyt','wall street journal','wsj','bloomberg','financial times',
  'the economist','washington post','the atlantic','barron','the information',
  'foreign policy','harvard business review','wired','new yorker','los angeles times',
  'chicago tribune','the times','sunday times','the telegraph','nikkei','caixin',
  'the australian','business insider','sydney morning herald','the age','forbes','ft.com'
];
const _pwRe = PAYWALLED.map(w=>new RegExp('(^|[^a-z0-9])'+w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'([^a-z0-9]|$)'));
function isPaywalled(src){
  const s=(src||'').toLowerCase().trim();
  if(!s) return false;
  return _pwRe.some(r=>r.test(s));
}

// fetch one feed fresh through a public CORS proxy (hits Google live => freshest)
async function fetchFeedProxy(f){
  const res = await proxied(f.url);
  const doc = new DOMParser().parseFromString(await res.text(),'text/xml');
  const now = Date.now();
  return Array.from(doc.getElementsByTagName('item')).slice(0,20).map(it=>{
    let title=(it.querySelector('title')||{}).textContent||'';
    let source=(it.querySelector('source')||{}).textContent||'';
    const m=title.match(/\s-\s([^-]+)$/);
    if(m && !source){ source=m[1].trim(); title=title.slice(0,m.index).trim(); }
    const pub=(it.querySelector('pubDate')||{}).textContent||'';
    const ts = pub? Date.parse(pub): now;
    const ago = Math.max(0, Math.round((now-(ts||now))/60000));
    return { title, source: source||'RSS', link:(it.querySelector('link')||{}).textContent||'', ts, ago: ago<1?'now':(ago<60?ago+'m':Math.round(ago/60)+'h') };
  }).filter(x=>x.title && !isPaywalled(x.source));
}
// fallback: Google News through the rss2json gateway (CORS, no key) if every proxy fails
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
    const ts = it.pubDate? Date.parse(it.pubDate): now;
    const ago = Math.max(0, Math.round((now-(ts||now))/60000));
    return { title, source: source||'RSS', link: it.link||'', ts, ago: ago<1?'now':(ago<60?ago+'m':Math.round(ago/60)+'h') };
  }).filter(x=>x.title && !isPaywalled(x.source));
}
async function loadNews(){
  $('#intelSrc').textContent = 'CONTACTING…';
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
  let items=[]; let okCount=0; let proxFeeds=0;
  settled.forEach((r,i)=>{
    if(r.list && r.list.length){ okCount++; if(r.via==='PROXY') proxFeeds++; items.push(...r.list.map(it=>({...it, region:NEWS_FEEDS[i].region, src:NEWS_FEEDS[i].src}))); }
  });
  if(!okCount){
    S.news = SAMPLE_ITEMS.map(it=>({...it,when:'now',ago:'0m'}));
    $('#intelSrc').textContent = 'RSS UNREACHABLE · SAMPLE';
  }else{
    // dedupe by title; sort newest-first; drop ancient leftovers so feed & map are live
    const cutoff = Date.now() - 48*60*60*1000;
    const seen = new Set();
    const recent = items.filter(it=> it.ts>=cutoff)
      .sort((a,b)=>b.ts-a.ts)
      .filter(it=>{ const k=(it.title||'').toLowerCase().trim(); if(!k||seen.has(k)) return false; seen.add(k); return true; });
    S.news = (recent.length ? recent : items.slice().sort((a,b)=>b.ts-a.ts)).slice(0,50);
    $('#intelSrc').textContent = 'LIVE · ' + (proxFeeds?'PROXY':'JSON');
    setStatus(true, 'STATUS: ONLINE — MARKETS + INTEL LIVE');
  }
  $('#feedFresh').textContent = 'updated '+new Date().toLocaleTimeString('en-GB');
  renderFeed();
  renderAlerts();
  renderBrief();
  renderWorld();
}
function renderFeed(){
  const list = S.news.slice(0,30);
  $('#feedCount').textContent = list.length + (S.news.length>30?'+':list.length===1?' item':' items');
  $('#feed').innerHTML = list.map(it=>`
    <a class="fitem" href="${esc(it.link)}" target="_blank" rel="noopener">
      <span class="when">${it.ago}</span>
      <span class="felem">
        <div class="ftitle">${esc(it.title)}</div>
        <div class="fmeta">
          <span class="tag region">${esc(it.region||'News')}</span>
          <span class="tag src">${esc(it.source||'')}</span>
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
  const top = alerts.slice(0,14).sort((x,y)=>sevRank[x.sev]-sevRank[y.sev]);
  const sevTxt={high:'HIGH',mid:'MED',low:'LOW'};
  const open = a.link ? ' · open ↗' : '';
  const cell = a => a.link
    ? `<a class="alert sev-${a.sev} alertlink" href="${esc(a.link)}" target="_blank" rel="noopener">
        <span class="sev">${a.label}</span>
        <span class="at">${a.when}</span>
        <div class="ab">
          <div class="atitle">${esc(a.title)}</div>
          <div class="asrc">${sevTxt[a.sev]} PRIORITY · ${esc(a.src||'')}${open}</div>
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
  // Region pulse (derived keyword heat)
  const regions=[
    ['Americas', ['america','washington','canada','brazil','us ','mexico']],
    ['Europe', ['europe','germany','france','uk','ukraine','russia','eu ','nato','brussels']],
    ['Middle East', ['iran','israel','gaza','saudi','qatar','iraq','syria','lebanon','middle east']],
    ['Asia-Pacific', ['china','japan','korea','taiwan','india','indonesia','australia','asia']],
    ['Africa', ['africa','niger','sudan','nigeria','kenya','ethiopia','sahel']],
    ['Global Markets', ['market','stock','fed','oil','inflation','dollar','bond','crypto']],
  ];
  $('#regionrow').innerHTML = regions.map(([name,kws])=>{
    const hits = S.news.filter(n=>kws.some(k=>(n.title||'').toLowerCase().includes(k))).length;
    const sev = hits===0?'':hits<=2?'warn':'crit';
    const temp = hits;
    const tags = S.news.filter(n=>kws.some(k=>(n.title||'').toLowerCase().includes(k))).slice(0,3)
      .map(n=>`<span class="tag region">${esc(n.region||'')}</span>`).join('') || '<span class="tag">quiet</span>';
    return `<div class="region ${sev}"><div class="rn"><span class="dot"></span>${name}</div>
      <div class="rtemp">${temp}<small> signals</small></div>
      <div class="rl">${temp? temp+' matching headline(s) in the live feed this cycle.':'No region-specific signal in current feed.'}</div>
      <div class="rtags">${tags}</div></div>`;
  }).join('');
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
let _map=null, _mapMarkers=[];
function hubRe(kws){ return new RegExp('\\b('+kws.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|')+')\\b'); }
function ensureMap(){
  if(_map || typeof L==='undefined') return _map;
  const el=$('#worldmap'); if(!el) return null;
  _map = L.map('worldmap',{ zoomControl:true, worldCopyJump:true, minZoom:2, maxZoom:8 });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
    attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains:'abcd', maxZoom:8
  }).addTo(_map);
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
    if(count>0) liveCount++;
    const color = count===0?'#334155':(count<=2?'#22c55e':(count<=4?'#f59e0b':'#ef4444'));
    const radius = 6 + Math.min(count,7)*2.3;
    const top = count>0 ? S.news[idx[0].i] : null;
    const m = L.circleMarker([lat,lng],{
      radius, color: count===0?'#334155':'#ffffff', weight:1,
      fillColor:color, fillOpacity: count===0?0.45:0.85
    }).addTo(map);
    m.bindPopup(count>0
      ? `<div class="mp-title">${esc(name)}</div>`+
        `<div class="mp-meta">${count} matching headline${count===1?'':'s'} in live feed</div>`+
        `<div style="margin-top:5px">${esc(top.title)}</div>`+
        `<div class="mp-meta" style="margin-top:2px"><a href="${esc(top.link)}" target="_blank" rel="noopener">open story ↗</a></div>`
      : `<div class="mp-title">${esc(name)}</div>`+
        `<div class="mp-meta">No ${esc(name)}-specific signal in the current feed.</div>`);
    _mapMarkers.push(m);
  });
  $('#mapCount').textContent = (liveCount||0)+' signal'+(liveCount===1?'':'s')+' live';
  $('#mapLegend').innerHTML =
    `<span class="li"><span class="sw" style="background:#334155"></span>quiet</span>`+
    `<span class="li"><span class="sw" style="background:#22c55e"></span>active</span>`+
    `<span class="li"><span class="sw" style="background:#f59e0b"></span>heightened</span>`+
    `<span class="li"><span class="sw" style="background:#ef4444"></span>elevated</span>`;
}
function wakeMap(){ ensureMap(); if(_map){ _map.invalidateSize(); } updateMapSignals(); }

/* ══════════════ WELCOME GUIDE ══════════════ */
const GUIDE=[
  {icon:'🛰️',h:'Welcome to World Monitor',p:'Your global intelligence workspace — live markets, geopolitical headlines, world clocks and risk signals synthesized into one screen.'},
  {icon:'📈',h:'Markets',p:'A live watchlist of major crypto assets with real prices, 24h changes and 7-day sparklines — pulled straight from public market data. The top ticker scrolls the full watchlist.'},
  {icon:'🕐',h:'World Clocks',p:'Real-time local time across 16 global cities and UTC — so you always know what hour it is in any major market or capital.'},
  {icon:'📰',h:'Intel Feed',p:'Live news headlines streamed from public RSS across world, markets, cyber, geopolitics and energy. Alerts auto-classify high-priority items.'},
  {icon:'🧭',h:'Use it',p:'Switch sections with the tabs (Markets · Intel · World · Alerts). Live data refreshes automatically. Beta — data may be delayed; verify critical intelligence independently.'},
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
  $$('.tab').forEach(t=>{
    t.addEventListener('click',()=>{
      $$('.tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')});
      t.classList.add('is-active');t.setAttribute('aria-selected','true');
      const v=t.dataset.view;
      $$('.view').forEach(s=>s.classList.toggle('is-active', s.id==='view-'+v));
      if(v==='world') setTimeout(wakeMap, 60);   // init/resize map once its container is visible
      try{ history.replaceState(null,'','#'+v); }catch(e){}
      window.scrollTo({top:0,behavior:'smooth'});
    });
  });
}

/* ══════════════ BOOT ══════════════ */
function boot(){
  bindTabs();
  // honor #view hash for initial section
  const want = (location.hash||'').replace('#','');
  if(['markets','intel','world','alerts'].includes(want)){
    const t=$(`.tab[data-view=${want}]`);
    if(t){ $$('.tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')});
      t.classList.add('is-active');t.setAttribute('aria-selected','true');
      $$('.view').forEach(s=>s.classList.toggle('is-active', s.id==='view-'+want)); }
    if(want==='world') setTimeout(wakeMap, 80);
  }
  $('#guideNext').addEventListener('click',nextGuide);
  $('#closeGuide').addEventListener('click',closeGuide);
  tickClocks(); setInterval(tickClocks,1000);
  loadMarkets(); setInterval(loadMarkets,60000);
  loadNews(); setInterval(loadNews,120000);   // intel refresh ~2m so headlines stay live
  loadPrediction(); setInterval(loadPrediction,300000);
  loadFX(); setInterval(loadFX,300000);
  // guide on first visit (skip when arriving via a section deep-link)
  if(!location.hash && !localStorage.getItem('wm_seen')){ openGuide(); localStorage.setItem('wm_seen','1'); }
  $('#helpBtn').addEventListener('click',openGuide);
  // page visibility keeps data honest on reload/tab-return
  document.addEventListener('visibilitychange',()=>{ if(!document.hidden){ tickClocks(); } });
}
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
else boot();
