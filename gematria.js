/* ══════════════════════════════════════════════════════════════════════════════
   GEMATRIA — Figurenlehre letter values + value-18 flagging
   ─────────────────────────────────────────────────────────────────────────────
   The chart below is the English variant of the Billy Meier / Plejaren
   Figurenlehre (the approximation Cheiro used). Word value = the sum of its
   letters' values; spaces and punctuation are ignored. A word counts as 18 in
   two ways:

     · SUM  — its letters total 18 (J1+E5+S3+U6+S3 = 18 → JESUS)
     · ENDS — the N.B. rule: its FIRST and LAST letters alone give 18, which
              takes 9+9, i.e. a word starting and ending on B, G or K
     · BOTH — both rules on the same word. Since the 9+9 ends already spend the
              whole 18, this can only be a two-letter word of two 9s (BK, KK, GB…) —
              such a word is flagged red so it never reads as a plain amber/blue.

   18 × 37 = 666, so every word flagged here is a 666-family hit.

   This file is self-contained so nothing else has to know the chart. It does
   two things:

     1. flags every 18 in the dashboard's own live headline corpus — the Intel
        feed snapshot (news.js), the public social snapshot (social.js) and the
        prophecy cards — inline in the feed/prophecy panels AND as the ledger
        table on the Gematria tab;
     2. exposes window.gmRender(), which app.js calls from its render pipeline
        right after renderFeed/renderProphecy, so the flags are re-applied on
        every refresh (see the render list inside loadNews()).

   Out of scope by design: tickers, prices, chart data, coordinates, camera
   names — the scan is headline text only.
   ══════════════════════════════════════════════════════════════════════════════ */
(function(){
  'use strict';

  /* ── the chart ─────────────────────────────────────────────────────────── */
  var C = {'C':1,'H':1,'I':1,'J':1,'T':1,'Y':1,   // 1
           'A':2,'R':2,                            // 2
           'S':3,                                  // 3
           'M':4,                                  // 4
           'D':5,'E':5,'L':5,'N':5,'Z':5,          // 5
           'P':6,'U':6,'V':6,'W':6,'X':6,          // 6
           'O':7,                                  // 7
           'F':8,'Q':8,                            // 8
           'B':9,'G':9,'K':9};                     // 9

  var WORD = /[A-Za-z]{2,}/g;

  function value(w){
    var u = String(w).toUpperCase(), s = 0;
    for(var i=0;i<u.length;i++){ var v = C[u[i]]; if(v) s += v; }
    return s;
  }
  function ends(w){
    var u = String(w).replace(/[^A-Za-z]/g,'').toUpperCase();
    if(u.length < 2) return 0;
    return (C[u[0]]||0) + (C[u[u.length-1]]||0);
  }
  function breakdown(w){
    var u = String(w).toUpperCase(), out = [];
    for(var i=0;i<u.length;i++){ var v = C[u[i]]; if(v) out.push(u[i]+v); }
    return out.join('+');
  }
  // 'both' = whole word AND first+last letters are 18, 'sum' = whole word is 18,
  // 'ends' = only first+last letters are 18, '' = not an 18.
  // Note the arithmetic: first+last = 18 already consumes two 9-valued letters
  // (B, G, K), and every other letter is worth at least 1, so 'both' can only
  // ever occur on a two-letter word made of two 9s (e.g. BK, KK, GB).
  function rule(w){
    var s = value(w) === 18, e = ends(w) === 18;
    if(s && e) return 'both';
    if(s) return 'sum';
    if(e) return 'ends';
    return '';
  }
  function words(text){ return String(text || '').match(WORD) || []; }

  /* ── German words ───────────────────────────────────────────────────────── */
  // The chart's values are language-specific (Contact Report 128): the German
  // assignment is the original one, so a flagged word that is a German word gets
  // a star. german-words.js ships only German words that are themselves 18s
  // (checked against a German frequency list, minus words that are also English)
  // — a word outside that list is simply not known to be German, not "not German".
  var DE = (function(){
    var raw = String(window.GM_DE || '').split(' '), set = {}, i;
    for(i=0;i<raw.length;i++){ if(raw[i]) set[raw[i]] = 1; }
    return set;
  })();
  function isGerman(w){ return DE[String(w).toUpperCase()] === 1; }

  function star(kind){
    // kind: 'sup' inside an inline mark, 'word' in the ledger table
    return kind === 'sup'
      ? '<sup class="gmde" title="German-language word — the chart\'s values are language-specific">★</sup>'
      : ' <span class="gmstar" title="German-language word">★</span>';
  }

  /* ── corpus: every headline the dashboard is currently carrying ─────────── */
  function corpus(){
    var out = [];
    function add(list, kind, fallbackSrc){
      if(!list || !list.length) return;
      for(var i=0;i<list.length;i++){
        var it = list[i];
        if(!it || !it.title) continue;
        out.push({ kind: kind, title: it.title,
                   src: it.source || it.src || it.platform || fallbackSrc || '',
                   region: it.region || it.platform || '',
                   link: it.link || '', ts: it.ts || 0 });
      }
    }
    add(window.NEWS   && window.NEWS.items,   'feed');
    add(window.SOCIAL && window.SOCIAL.items, 'social');
    add(window.PROPHECIES,                    'prophecy', 'PROPHECY');
    return out;
  }

  /* ── scan the corpus for 18s ───────────────────────────────────────────── */
  function scan(){
    var items = corpus(), hits = [], byWord = {}, flaggedItems = 0, i, j;
    for(i=0;i<items.length;i++){
      var ws = words(items[i].title), itemHas = false;
      for(j=0;j<ws.length;j++){
        var r = rule(ws[j]);
        if(!r) continue;
        var w = ws[j].toUpperCase();
        hits.push({ word: w, rule: r, v: value(w), e: ends(w), br: breakdown(w), item: items[i] });
        byWord[w] = (byWord[w] || 0) + 1;
        itemHas = true;
      }
      if(itemHas) flaggedItems++;
    }
    return { hits: hits, byWord: byWord, items: items.length, flaggedItems: flaggedItems,
             updated: (window.NEWS && window.NEWS._updated) || '' };
  }

  /* ── inline flags: mark every 18 inside a rendered headline text node ───── */
  function markText(root){
    if(!root || root.dataset.gmDone || !root.firstChild) return 0;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [], n;
    while((n = walker.nextNode())) nodes.push(n);
    var total = 0;
    for(var k=0;k<nodes.length;k++){
      var node = nodes[k], txt = node.nodeValue;
      if(!txt || txt.length < 2) continue;
      var frag = null, last = 0, m;
      WORD.lastIndex = 0;
      while((m = WORD.exec(txt))){
        var r = rule(m[0]);
        if(!r) continue;
        if(!frag) frag = document.createDocumentFragment();
        frag.appendChild(document.createTextNode(txt.slice(last, m.index)));
        var w = m[0].toUpperCase();
        var de = isGerman(w);
        var mk = document.createElement('mark');
        mk.className = 'gm18' + (r === 'ends' ? ' gm-ends' : r === 'both' ? ' gm-both' : '');
        mk.textContent = m[0];
        mk.title = (r === 'both')
          ? breakdown(w) + ' = 18 (whole word) AND first + last letter = 18  ·  18 × 37 = 666'
          : (r === 'sum')
          ? breakdown(w) + ' = 18  ·  18 × 37 = 666'
          : 'first + last letter = ' + w[0] + '(' + (C[w[0]]||0) + ') + ' + w[w.length-1] +
            '(' + (C[w[w.length-1]]||0) + ') = 18  ·  18 × 37 = 666';
        if(de) mk.title += '  ·  German word';
        frag.appendChild(mk);
        if(de){
          var sup = document.createElement('sup');
          sup.className = 'gmde';
          sup.textContent = '★';
          sup.title = 'German-language word — the chart\'s values are language-specific';
          frag.appendChild(sup);
        }
        last = m.index + m[0].length;
        total++;
      }
      if(frag){
        frag.appendChild(document.createTextNode(txt.slice(last)));
        node.parentNode.replaceChild(frag, node);
      }
    }
    root.dataset.gmDone = '1';
    return total;
  }

  function markAll(){
    var n = 0;
    var targets = ['#feed .ftitle', '#proplist .ptitle', '#alertlist .atitle'];
    for(var i=0;i<targets.length;i++){
      var els = document.querySelectorAll(targets[i]);
      for(var j=0;j<els.length;j++) n += markText(els[j]);
    }
    return n;
  }

  /* ── ledger table on the Gematria tab ──────────────────────────────────── */
  function esc(s){
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function renderLedger(sc){
    var box = document.getElementById('gmLedger');
    var cnt = document.getElementById('gmCount');
    var src = document.getElementById('gmSrc');
    if(src) src.textContent = sc.updated ? ('SCAN · FEED ' + sc.updated) : 'HEADLINE SCAN';
    if(!box) return;
    if(!sc.items){
      if(cnt) cnt.textContent = '—';
      box.innerHTML = '<div class="ph mono" style="padding:16px">No headline corpus loaded yet — the feed snapshot has not arrived.</div>';
      return;
    }
    var wordList = Object.keys(sc.byWord).sort(function(a, b){
      return (sc.byWord[b] - sc.byWord[a]) || (a < b ? -1 : 1);
    });
    var bothWords = wordList.filter(function(w){ return rule(w) === 'both'; });
    var deWords = wordList.filter(isGerman);
    if(cnt) cnt.textContent = sc.hits.length + ' hits · ' + wordList.length + ' words · ' +
                              sc.flaggedItems + ' of ' + sc.items + ' headlines' +
                              (bothWords.length ? ' · ' + bothWords.length + ' both' : '') +
                              (deWords.length ? ' · ' + deWords.length + ' ★' : '');
    var rows = wordList.map(function(w){
      var r = rule(w);
      var cls = r === 'both' ? 'gm-both' : (r === 'sum' ? 'gm-sum' : 'gm-ends');
      var lab = r === 'both' ? 'sum + first+last' : (r === 'sum' ? 'sum 18' : 'first+last 18');
      return '<tr>' +
        '<td class="gmword">' + w + (isGerman(w) ? star('word') : '') + '</td>' +
        '<td><span class="gmbadge ' + cls + '">' + lab + '</span></td>' +
        '<td class="gmbr mono">' + breakdown(w) + ' = ' + value(w) + '</td>' +
        '<td class="right num">' + sc.byWord[w] + '</td>' +
      '</tr>';
    }).join('');
    box.innerHTML =
      '<div class="gmsum mono">' + sc.hits.length + ' flagged instances · ' + wordList.length +
        ' distinct words · ' + sc.flaggedItems + ' of ' + sc.items + ' headlines carry one' +
        (bothWords.length ? ' · <span class="gmlegend gm-both">' + bothWords.length +
          ' satisfy both rules</span>' : '') +
        (deWords.length ? ' · <span class="gmlegend gm-de">' + deWords.length +
          ' ★ German</span>' : '') + '</div>' +
      '<div class="tablewrap"><table class="dt">' +
        '<thead><tr><th>Word</th><th>18 by</th><th>Arithmetic</th><th class="right">Hits</th></tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table></div>';
  }

  /* ── public entry point ────────────────────────────────────────────────── */
  function gmRender(){
    var sc;
    try{ sc = scan(); }catch(e){ return 0; }
    var inline = 0;
    try{ inline = markAll(); }catch(e){}
    try{ renderLedger(sc); }catch(e){}
    return inline;
  }
  window.gmRender = gmRender;
  // console handles: GM.value('JESUS') → 18, GM.isGerman('GOTT') → true
  window.GM = { value: value, ends: ends, rule: rule, breakdown: breakdown,
                isGerman: isGerman, scan: scan, render: gmRender };

  function init(){ try{ gmRender(); }catch(e){} }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  // the corpus arrives with the async feed load; re-run a couple of times so the
  // tab is populated even if the user opens it before the first render pass
  setTimeout(init, 1500);
  setTimeout(init, 6000);
})();
