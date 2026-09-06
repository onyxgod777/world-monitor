/* ═══════════════════════════════════════════════════════════════════
   WORLD MONITOR — Live Causal Prophecy Engine (live-prophesy.js)

   Replaces the pi-mirrored prophecies.js. Derives prophecies/predictions
   DIRECTLY from World Monitor's own live Intel headlines via a deterministic
   causal-inference algorithm, applying the Wechselwirkung causal law as the
   working lens (cause → accumulated same-kind → effect; the hinge = the free-will
   choice that rewrites the cause). The law is understood and applied — not quoted.

   Honest framing: this is causal inference over a live headline feed, NOT
   fortune-telling. Every card names the observed cause (the real headlines now
   on the feed), projects the necessary effect IF that cause persists/compounds,
   and names the hinge (the decision that changes the effect).

   Pure client-side, deterministic, no network calls, no LLM. Recomputes each
   time the Intel feed refreshes, so it always tracks what is actually live.
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

(function () {
  /* ── Causal themes. Order matters: first regex match wins per headline. ──
     Each theme maps a live cause (the headlines it catches) to its projected
     necessary effect and its hinge (the reversal condition). The framing applies
     the Wechselwirkung causal law internally; no scripture is rendered.       */
  const THEMES = [
    {
      key: 'conflict', emoji: '🔥', tag: 'CONFLICT · GEOPOLITICS', cls: 'red',
      kw: ['iran', 'hormuz', 'tehran', 'gulf', 'israel', 'gaza', 'west bank', 'houthi', 'military', 'missile',
           'drone', 'strike', 'war', 'troops', 'invasion', 'ceasefire', 'rebel', 'offensive', 'bomb', 'retali',
           'escalat', 'conflict', 'sanction', 'blockade', 'ukraine', 'russia', 'moscow', 'kyiv', 'putin', 'nato'],
      causeLead: 'an active confrontation is compounding — strikes, blockades and retaliatory moves are being met with the same kind, so the conflict is accumulating energy rather than winding down',
      bullets: [
        '**Escalation tends to call forth escalation** — the direct effect of ongoing strikes and retaliatory responses is that each side answers the previous move, raising the intensity and geographic reach of the confrontation while any off-ramp is deferred',
        '**The human and economic cost compounds even in lulls** — because the confrontation persists, displacement, disrupted trade and civilian strain keep building in and beyond the affected region, and that accumulation feeds the next phase rather than resolving it',
        '**Sanctions and blockades harden into standing architecture** — the longer economic pressure and closed routes are treated as instruments of war, the more they become recurring leverage in future disputes, converting what was once exceptional into a standing cost',
      ],
      hinge: 'The effect is not fixed. It is being written by the choice of the parties to keep escalating — or to de-escalate: a revived ceasefire, a negotiated settlement that addresses the root grievance, and a return to dialogue over force. Because the law is one of attraction of same-kinds, the move that changes the cause — restraint where retaliation is expected — is the move that rewrites the effect. That choice is available now, in every capital on both sides.'
    },
    {
      key: 'markets', emoji: '📉', tag: 'MARKETS · RATES', cls: 'amber',
      kw: ['fed', 'rate', 'inflation', 'bond', 'yield', 'treasury', 'recession', 'market', 'stock', 'sell-off',
           'dollar', 'debt', 'gdp', 'tariff', 'trade war', 'central bank', 'stocks', 'oil price', 'crude', 'rally'],
      causeLead: 'financial markets are repricing on the same set of pressures — rate expectations, inflation and geopolitical risk — and that repricing is being reinforced by the very uncertainty it feeds',
      bullets: [
        '**Expectations become the transmission mechanism** — the direct effect of rate and inflation concerns is that borrowing costs, equity valuations and currency moves all swing on the next data point, amplifying volatility whenever guidance shifts',
        '**Risk is shared but not evenly** — because the pressure is global, developed and emerging markets transmit the shock to one another, and the economies with thinner buffers feel the repricing first and hardest',
        '**Policy becomes the hinge that tips the balance** — the longer markets hinge on one expected move, the more a single central-bank decision or trade de-escalation can reverse the mood, making the direction depend on choices not yet made',
      ],
      hinge: 'Markets are not forecasting; they are reacting to a chain of expected moves that are themselves decisions still open. The effect changes with the choice: a central bank that calibrates rather than over-corrects, and trade disputes that move toward agreement rather than retaliation, change the cause and therefore the projected effect. No repricing is inevitable — each is the echo of a decision that can be made differently.'
    },
    {
      key: 'cyber', emoji: '🛡️', tag: 'CYBER · SECURITY', cls: 'amber',
      kw: ['cyber', 'hack', 'breach', 'ransom', 'zero-day', 'malware', 'phishing', 'data leak', 'ransomware', 'exploit'],
      causeLead: 'a digital intrusion or exploit is active — systems are being probed or compromised, and the response will shape whether the damage stays contained or propagates',
      bullets: [
        '**Compromised trust spreads faster than the breach itself** — the direct effect of a confirmed intrusion is that customers, partners and regulators reprice their exposure, and that loss of confidence outlasts the technical fix',
        '**A single compromised seam can cascade** — because modern systems are interconnected, the effect of an exploit is not only the direct victim but every downstream dependency sharing the same credentials, vendor or protocol',
        '**The reaction determines the recurrence** — the effect of an incident handled by patching, disclosure and hardening is a contained lesson; handled by concealment, it invites the same kind back against the same weakness',
      ],
      hinge: 'A breach is a cause that has already been set in motion, but its effect is still being chosen. Transparent disclosure, rapid patching and treating the lesson as systemic — not blaming a single user — change whether the same-kind is attracted again. The technical fix matters; the institutional response decides how far the effect travels.'
    },
    {
      key: 'climate', emoji: '🌪️', tag: 'CLIMATE · WEATHER', cls: 'amber',
      kw: ['el nino', 'enso', 'climate', 'warming', 'drought', 'wildfire', 'flood', 'storm', 'typhoon', 'hurricane',
           'heat', 'weather', '1.5c', 'sea level', 'cyclone', 'monsoon'],
      causeLead: 'a climatic extreme is unfolding or intensifying — and because such events are amplified by the conditions that bred them, the present disruption carries the seed of the next',
      bullets: [
        '**Compounding events outrun single responses** — the direct effect of an unfolding extreme (drought, flood, storm) is that it stresses food, water and energy systems at once, and each stress amplifies the others in the same region',
        '**Displacement and loss precede the reconstruction debate** — because the event is physical, the effect is immediate human and economic dislocation, and the communities least able to absorb it are hit hardest first',
        '**The pattern persists until the cause is changed** — the longer the underlying drivers continue, the more such events accumulate as a recurring ordeal rather than a one-off, each hardening the exposure of the next',
      ],
      hinge: 'The storm is not the whole cause — the accumulated conditions that made it destructive are. Those conditions are shaped by choices still being made: how fast emissions are cut, how infrastructure and communities are hardened, and whether warnings become action. Changing that longer cause changes the severity of every future effect, even if this event must now be endured.'
    },
    {
      key: 'energy', emoji: '🛢️', tag: 'ENERGY · COMMODITIES', cls: 'amber',
      kw: ['oil', 'energy', 'crude', 'gas', 'commodit', 'supply', 'chokepoint', 'shipping', 'cargo', 'refinery', 'opec', 'pipeline', 'tanker', 'red sea', 'hormuz'],
      causeLead: 'an energy-supply pressure is tightening — a chokepoint, a trade restriction or a demand shock is being transmitted through prices and then back through every economy that depends on it',
      bullets: [
        '**Prices transmit a single shock everywhere** — the direct effect of a supply disruption at a chokepoint or producer is that crude and gas costs rise globally, feeding inflation into transport, industry and consumers far from the source',
        '**Routes closed in one crisis become leverage in the next** — because shipping lanes and pipelines are now treated as instruments of pressure, the effect of today\u2019s disruption is a standing lesson that any artery can be weaponised, raising risk premia permanently',
        '**Diversification is the slow answer to a fast problem** — the longer reliance on one route or producer persists, the more exposed the system is to the next closure, until redundancy is built or the pressure is relieved',
      ],
      hinge: 'An energy shock is not destiny. It is the product of choices about how the world moves and powers itself — whether chokepoints are kept open by agreement rather than contested by force, and whether dependence is diversified before the next disruption. Those choices are open now, and they decide whether this pressure compounds into a systemic shock or stays a contained cost.'
    },
    {
      key: 'diplomacy', emoji: '🤝', tag: 'GEOPOLITICS · SIGNAL', cls: 'blue',
      kw: ['talks', 'summit', 'diplomacy', 'negotiat', 'deal', 'accord', 'treaty', 'ceasefire talks', 'mediation',
           'ambassador', 'foreign minister', 'alliance', 'agreement', 'trade deal', 'dialogue'],
      causeLead: 'a diplomatic process is in motion — and its trajectory will be set less by the talks themselves than by whether the parties treat them as a real off-ramp or as a stalling tactic',
      bullets: [
        '**Good-faith talks change the field; performative talks do not** — the direct effect of a genuine negotiation is that it opens paths that force does not; one used only for cover leaves the underlying cause untouched and the confrontation ready to resume',
        '**Every concession builds or burns trust** — because negotiation is iterative, the effect of each step is to make the next agreement easier or harder, compounding toward a durable settlement or toward collapse',
        '**The window is real but not open-ended** — the longer talks run without addressing the core grievance, the more the same-kind energy on the ground accumulates and the harder any eventual agreement becomes',
      ],
      hinge: 'Diplomacy only works when the cause changes. The hinge is whether the parties negotiate in good faith toward the root issue — and are willing to make the concessions that prove it — or use the table to buy time while the underlying confrontation continues. That choice, made in the talks and honoured outside them, decides whether this process rewrites the effect or merely postpones it.'
    },
  ];

  function escTitle(t) {
    return (t || '').replace(/\s+/g, ' ').trim();
  }
  function clip(s, n) {
    s = (s || '').trim();
    if (s.length <= n) return s;
    const cut = s.slice(0, n); const sp = cut.lastIndexOf(' ');
    return (sp > 40 ? cut.slice(0, sp) : cut).replace(/\s+$/, '') + '…';
  }

  // Assign each live headline to its first matching causal theme.
  // Classified on the TITLE ONLY (word-boundary keyword match) so a story is
  // grouped by what it is actually about, not by which feed/region carried it
  // and not by a keyword substring inside an unrelated word ("war" in "reward").
  const _reCache = {};
  function themeRx(th) {
    if (!_reCache[th.key]) {
      const esc = w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      _reCache[th.key] = new RegExp('\\b(?:' + th.kw.map(esc).join('|') + ')\\b', 'i');
    }
    return _reCache[th.key];
  }
  function classify(items) {
    const groups = {};
    items.forEach(it => {
      const title = escTitle(it.title);
      if (!title) return;
      for (const th of THEMES) {
        if (themeRx(th).test(title)) { (groups[th.key] = groups[th.key] || []).push(it); break; }
      }
    });
    // sort by coverage descending so the strongest live signal leads
    return THEMES
      .filter(th => (groups[th.key] || []).length)
      .sort((a, b) => groups[b.key].length - groups[a.key].length)
      .map(th => ({ theme: th, items: groups[th.key] }));
  }

  // words of the headline that actually tripped this theme (for coherence checks)
  function matchedTokens(th, title) {
    return th.kw.filter(k => new RegExp('\\b' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b', 'i').test(title));
  }
  function buildCause(th, items) {
    const sorted = items.slice().sort((a, b) => (b.ts || 0) - (a.ts || 0));
    const first = sorted[0];
    // Secondary evidence is only cited when it is coherent with the lead — it must
    // share at least one keyword that tripped this theme, so we never pair a story
    // with an unrelated headline just because both landed in the same broad theme.
    const shared = matchedTokens(th, first.title).join('|');
    const second = shared
      ? sorted.find(it => it !== first && new RegExp('\\b(?:' + shared.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')\\b', 'i').test(it.title))
      : null;
    const lead = `Live intel is tracking **“${clip(first.title, 150)}”** — ${first.source} (${first.ago})`
      + (second ? `, joined by **“${clip(second.title, 140)}”** — ${second.source} (${second.ago})` : '')
      + (items.length > 1 ? ` — one of ${items.length} related item${items.length === 1 ? '' : 's'} on the feed touching this thread.` : '.');
    return `${lead} The observed cause — the active development feeding this prediction — is that ${th.causeLead}.`;
  }

  function buildOne(th, items) {
    const kw = th.kw;
    // title derives from the strongest live headline so each card is grounded in a real current story
    const top = items.slice().sort((a, b) => (b.ts || 0) - (a.ts || 0))[0];
    const title = `${th.emoji} ${clip(top.title, 160)}`;
    return {
      emoji: th.emoji,
      title: title,
      short: clip(top.title, 115),
      tag: th.tag,
      cls: th.cls,
      kw: kw,
      cause: buildCause(th, items),
      bullets: th.bullets,
      hinge: th.hinge,
      _evidence: items.length,
    };
  }

  // Public entry: news = the live S.news items {title, source, region, ago, ts}
  function buildLiveProphecies(news) {
    const list = Array.isArray(news) ? news : [];
    const groups = classify(list);
    const records = groups.slice(0, 6).map(g => buildOne(g.theme, g.items));
    const now = new Date();
    const updated = now.toISOString().slice(0, 16).replace('T', ' ');
    return Object.assign(records, { _updated: updated, _count: records.length });
  }

  const g = typeof window !== 'undefined' ? window : globalThis;
  g.buildLiveProphecies = buildLiveProphecies;
})();
