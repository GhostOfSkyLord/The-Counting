"use strict";
/* The Counting: the interface. Talks to the local Python server; everything shown here comes from /api. */
const TOKEN = document.querySelector('meta[name="tally-token"]').content;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, method, body) {
  let r;
  const attempts = (method || "GET") === "GET" ? 3 : 1;  // reads are safe to repeat; marks are not
  try {
    for (let i = 0; i < attempts; i++) {
      try {
        r = await fetch(path, {
          method: method || "GET",
          headers: { "X-Tally-Token": TOKEN, "Content-Type": "application/json" },
          body: body !== undefined ? JSON.stringify(body) : undefined,
        });
        break;
      } catch (e) { if (i === attempts - 1) throw e; await new Promise(res => setTimeout(res, 600)); }
    }
  } catch (e) {
    const err = new Error("This window lost contact with The Counting's engine (not TMDB). Close The Counting and open it again. If it keeps happening, run the connection check in Settings, or open The Counting's data folder (Settings, Help) and look at thecounting.log.");
    err.kind = "engine"; throw err;
  }
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) { const err = new Error(data.error || "Something went wrong."); err.kind = data.kind; throw err; }
  return data;
}

const S = {
  view: "library", app: null, lib: "watching", libData: null, toData: null, sortReady: true, readyOnly: false,
  show: null, open: {}, revealed: {}, modal: null, menu: false, keep: {}, castCounts: false,
  search: { q: "", results: null, err: null, seen: false }, stats: null, log: null, backups: null, pendingImport: null,
  self: null, guide: null, tour: null, offer: false, fold: {}, lan: null, pair: null, seq: {}, disc: null, discMode: "you", rt: { tab: "ranks", profile: null, rank: null, scope: "overall", arena: null, favs: null, arenaScope: "overall", round: { n: 0, total: 5, active: false, done: false } }, draft: null, sdraft: null,
};

/* ---------- small helpers ---------- */
function toast(t) {
  const e = $("#toast"); e.textContent = t; e.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(() => { e.style.display = "none"; }, 3600);
}
const mix = id => (Math.imul(id | 0, 2654435761) >>> 0) >>> 3;  // a small hash so ids that are close together get different colours
const inits = n => String(n).replace(/[^A-Za-z0-9 ]/g, "").split(" ").filter(Boolean).map(s => s[0]).join("").slice(0, 2).toUpperCase();
function poster(s, cls) {
  const big = cls === "lg";
  return '<div class="poster ' + (cls || "") + '" data-k="' + (mix(s.id) % 4) + '" data-s="' + (Math.floor(mix(s.id) / 4) % 3) + '" aria-hidden="true"><span>' + esc(inits(s.name)) + "</span>" +
    (s.poster_path ? '<img loading="lazy" alt="" src="/img/' + (big || cls === "fill" || cls === "xl" ? "w342" : "w185") + s.poster_path + '" onerror="this.remove()">' : "") + "</div>";
}
const when = sec => new Date(sec * 1000).toLocaleString();
const kb = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
const epTitle = (x) => x.name != null ? esc(x.name) : '<span class="muted">Title hidden</span>';

async function run(fn) {
  try { return await fn(); }
  catch (e) {
    if (e.kind === "nokey") { S.view = "setup"; render(); return; }
    if (e.kind === "auth") { S.view = "settings"; S.settingsErr = e.message; render(); return; }
    toast(e.message); return undefined;
  }
}

/* ---------- theme ---------- */
const systemDark = () => !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
const effectiveTheme = () => { const t = S.app ? S.app.theme : "system"; return t === "system" ? (systemDark() ? "dark" : "light") : t; };
function applyTheme(t) { const r = document.documentElement; if (t === "light" || t === "dark") r.setAttribute("data-theme", t); else r.removeAttribute("data-theme"); }
async function setTheme(t) {
  if (S.app && S.app.remote) { try { localStorage.setItem("tc-theme", t); } catch (e) { /* private mode */ } S.app.theme = t; applyTheme(t); return render(); }
  await run(async () => { S.app = await api("/api/settings/theme", "POST", { theme: t }); }); if (S.app) applyTheme(S.app.theme); render();
}
const themeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/></svg>';

/* ---------- loading ---------- */
async function refreshState() { S.app = await api("/api/state"); }
async function load(view) {
  // Each load gets a number. If a newer load for the same view starts, the older one is dropped when it
  // finishes, so a slow earlier request can never overwrite a newer answer.
  const seq = S.seq[view] = (S.seq[view] || 0) + 1;
  const fresh = () => seq === S.seq[view];
  if (view === "library") {
    const r = await api("/api/library?status=" + S.lib);
    let g = null; try { g = await api("/api/guide"); } catch (e) { /* guidance is optional */ }
    if (fresh()) { S.libData = r; if (g && S.guide) { S.guide.progress = g.progress; if (!S.app.remote) S.guide.state = g.state; } }
  }
  else if (view === "towatch") { const r = await api("/api/towatch"); if (fresh()) S.toData = r; }
  else if (view === "show") { const r = await api("/api/shows/" + S.showId); if (fresh()) S.show = r; }
  else if (view === "stats") { const r = await api("/api/stats"); if (fresh()) S.stats = r; }
  else if (view === "log") { const r = (await api("/api/log?limit=150")).events; if (fresh()) S.log = r; }
  else if (view === "data") { const r = await api("/api/backups"); if (fresh()) S.backups = r; }
  else if (view === "settings") { if (!(S.app && S.app.remote)) { const r = await api("/api/lan"); if (fresh()) S.lan = r; } }
  else if (view === "discover") {
    guideVisit("discover");
    const path = "/api/discover?mode=" + S.discMode;
    let out = await api(path);
    for (let i = 0; i < 6 && out.pending > 0 && fresh(); i++) out = await api(path);  // fetches a few shows' links per call
    if (fresh()) S.disc = out;
  }
  else if (view === "ratings") {
    const rt = S.rt, tab = rt.tab, scope = rt.scope;
    if (tab === "arena") guideVisit("arena");
    const profile = await api("/api/ratings/profile");
    let rank, arena, favs;
    if (tab === "ranks") rank = await api("/api/ratings/rankings?scope=" + scope);
    else if (tab === "arena") arena = await api("/api/ratings/arena?scope=" + rt.arenaScope);
    else if (tab === "favs") favs = (await api("/api/favourites")).favourites;
    if (fresh()) { rt.profile = profile; if (rank) rt.rank = rank; if (arena) rt.arena = arena; if (favs) rt.favs = favs; }
  }
}
async function go(view, extra) {
  S.menu = false; S.modal = null;
  Object.assign(S, extra || {});
  S.view = view;
  await run(async () => { await refreshState(); await load(view); });
  render(); window.scrollTo(0, 0);
}
async function reload() { await run(async () => { await refreshState(); await load(S.view); }); render(); }

/* ---------- views ---------- */
function vSetup() {
  return '<div class="setup"><div class="welcome" aria-hidden="true"><div class="waves"></div><div class="sun"></div><svg class="shapes" viewBox="0 0 150 52"><polygon points="3,49 25,5 47,49" fill="var(--yellow)" stroke="var(--ink)" stroke-width="3"/><rect x="58" y="10" width="38" height="38" fill="var(--red)" stroke="var(--ink)" stroke-width="3"/><circle cx="125" cy="29" r="19" fill="var(--blue)" stroke="var(--ink)" stroke-width="3"/></svg></div><h1>Welcome to The Counting</h1><p class="sub">The Counting keeps your shows and progress on this computer. It needs a free TMDB account for show information such as episode lists and artwork.</p>' +
    '<div class="panel" style="margin-top:1rem"><h3>Get your TMDB key</h3><ol><li>Create a free account at <button class="link" data-a="tmdb-api">themoviedb.org</button> and open <b>Settings, then API</b>.</li><li>Request an API key for personal use.</li><li>Copy the <b>API Key</b> (or the longer <b>API Read Access Token</b>) and paste it below.</li></ol>' +
    (S.settingsErr ? '<div class="err">' + esc(S.settingsErr) + "</div>" : "") +
    '<div class="field"><label for="key">TMDB API key</label><input id="key" type="password" autocomplete="off" spellcheck="false"></div><button class="btn pri" data-a="savekey">Save and continue</button>' +
    '<p class="meta" style="margin-top:.8rem">The key stays on this computer. The Counting uses it only to talk to TMDB. Trouble saving it? <button class="link" data-a="diagnose">Run a connection check</button>.</p><div id="diag"></div></div></div>';
}
/* One square per episode: teal for watched, a red outline for the one to watch next, hatched for not aired yet.
   Long shows are shown at 48 squares at most, each standing for several episodes. */
function countSquares(s) {
  const total = Math.max(0, s.episodes || 0), aired = s.progress.total, watched = s.progress.watched;
  if (!total) return "";
  const n = Math.min(total, 48), per = total / n, filled = Math.floor(watched / per + 1e-9);
  const nextAt = s.next ? Math.min(n - 1, Math.floor(watched / per + 1e-9)) : -1, unaired = Math.ceil(aired / per - 1e-9);
  let h = '<div class="sq ' + (n <= 10 ? "lg" : n <= 24 ? "md" : "") + '" role="img" aria-label="' + watched + " of " + aired + ' aired episodes watched">';
  for (let i = 0; i < n; i++) h += '<i class="' + (i < filled ? "on" : i === nextAt ? "next" : i >= unaired ? "un" : "") + '"></i>';
  return h + "</div>";
}
function libCard(s) {
  const p = s.progress;
  let bot;
  if (s.loading) bot = '<span class="meta">Fetching show data. This can take a moment.</span>';
  else if (s.next) bot = '<div class="nextinfo"><span class="meta">Next up</span><span class="nt"><b>' + esc(s.next.label) + "</b> " + (s.next.name != null ? esc(s.next.name) : '<i class="meta">title hidden</i>') + '</span></div><button class="btn pri" data-a="mark" data-id="' + s.next.id + '" aria-label="Mark ' + esc(s.next.label) + ' watched">Mark watched</button>';
  else bot = '<div class="nextinfo"><span class="nt">' + (s.state ? '<span class="badge acc">' + s.state + "</span> " + (s.state === "Up to date" ? "Waiting for new episodes" : "Nothing left to watch") : "No episodes to watch yet") + "</span></div>" + (s.state === "All watched" && !s.rating ? '<button class="btn pri" data-a="rateshow" data-id="' + s.id + '">Rate it</button>' : "");
  return '<article class="lcard"><button class="art" data-a="open" data-id="' + s.id + '" aria-label="Open ' + esc(s.name) + '">' + poster(s, "fill") + '<span class="tag">' + esc(s.tmdb_status) + '</span></button><div class="info"><h2><button class="back" style="text-decoration:none;color:inherit;padding:0;font:inherit;text-align:left" data-a="open" data-id="' + s.id + '">' + esc(s.name) + "</button></h2>" +
    '<div class="meta">' + s.seasons + " season" + (s.seasons === 1 ? "" : "s") + ", " + s.episodes + " episodes." + (s.rating ? " Your rating: <b>" + esc(s.rating) + "</b>." : "") + "</div>" + countSquares(s) +
    '<div class="meta">' + p.watched + " of " + p.total + " aired episodes watched</div></div>" + (s.loading ? '<div class="bot">' + bot + "</div>" : '<div class="bot">' + bot + "</div>") + "</article>";
}
function syncNote() {
  return S.app && S.app.pending_sync ? '<div class="syncnote">Fetching show data in the background (' + S.app.pending_sync + " left)...</div>" : "";
}
function vLibrary() {
  const d = S.libData; if (!d) return '<div class="spin">Loading...</div>';
  const tabs = [["watching", "Watching"], ["hold", "On hold"], ["dropped", "Dropped"], ["completed", "Completed"]];
  let h = '<div class="head"><div><h1>Library</h1><p class="sub">Shows you have started. Tap Mark watched to log your next episode.</p></div><button class="btn pri" data-a="nav" data-id="search">Add a show</button></div>' + syncNote() + guideChecklist();
  if (S.lib === "watching") d.shows.filter(s => s.state === "All watched" && !S.keep[s.id]).forEach(s => {
    h += '<div class="banner"><span>You have watched every episode of <b>' + esc(s.name) + '</b>, and it has ended. Mark it completed?</span><span class="row"><button class="btn pri sm" data-a="complete" data-id="' + s.id + '">Mark completed</button><button class="btn sm" data-a="keep" data-id="' + s.id + '">Not yet</button></span></div>';
  });
  h += '<div class="chips" role="group" aria-label="Status filter">' + tabs.map(t => '<button class="chip" aria-pressed="' + (S.lib === t[0]) + '" data-a="lib" data-id="' + t[0] + '">' + t[1] + " (" + (d.counts[t[0]] || 0) + ")</button>").join("") + "</div>";
  if (!d.shows.length) {
    h += '<div class="empty">' + (S.lib === "watching" && !(d.counts.plan || d.counts.hold || d.counts.dropped || d.counts.completed)
      ? 'Your library is empty. <button class="link" data-a="nav" data-id="search">Add your first show</button> to get started.'
      : "Nothing here yet. Shows you move to this status will appear in this list.") + "</div>";
  }
  return h + '<div class="pgrid">' + d.shows.map(libCard).join("") + "</div>";
}
function vToWatch() {
  const d = S.toData; if (!d) return '<div class="spin">Loading...</div>';
  let list = d.shows.slice();
  if (S.readyOnly) list = list.filter(s => s.readiness.kind === "ready");
  const rank = { ready: 0, maybe: 1, wait: 2, unknown: 3 };
  if (S.sortReady) list.sort((a, b) => rank[a.readiness.kind] - rank[b.readiness.kind]); else list.sort((a, b) => a.hours - b.hours);
  let h = '<div class="head"><div><h1>To watch</h1><p class="sub">Shows you plan to start. Ready shows come first, so you can pick a binge.</p></div><button class="btn pri" data-a="nav" data-id="search">Add a show</button></div>' + syncNote() +
    '<div class="chips" role="group" aria-label="Sort and filter"><button class="chip" aria-pressed="' + S.sortReady + '" data-a="sortready">Ready first</button><button class="chip" aria-pressed="' + !S.sortReady + '" data-a="sortshort">Shortest first</button><button class="chip" aria-pressed="' + S.readyOnly + '" data-a="readyonly">Ready only</button></div>';
  if (!list.length) h += '<div class="empty">' + (d.shows.length ? 'No shows match. Turn off "Ready only".' : 'Your watch list is empty. <button class="link" data-a="nav" data-id="search">Find a show to add</button>.') + "</div>";
  return h + '<div class="grid">' + list.map(s => '<article class="card">' + poster(s) + '<div class="body"><div class="row" style="justify-content:space-between"><h3><button class="back" style="text-decoration:none;color:inherit;padding:0;font:inherit;text-align:left" data-a="open" data-id="' + s.id + '">' + esc(s.name) + '</button></h3><span class="badge ' + (s.readiness.kind === "ready" ? "ready" : "") + '">' + esc(s.readiness.text) + '</span></div><p class="sub">' + esc(s.overview) + '</p><div class="meta" style="margin-top:.4rem">' + s.seasons + " season" + (s.seasons === 1 ? "" : "s") + ", " + s.episodes + " episodes, about " + s.hours + " hours. " + esc(s.genres.join(", ")) + ".</div></div></article>").join("") + "</div>";
}
function vSearch() {
  return '<div class="head"><div><h1>Add a show</h1><p class="sub">Search TMDB, then add the show to your watch list, start tracking it, or record one you have already watched.</p></div></div>' + (S.search.seen ? '<div class="syncnote">Search for a show you watched before The Counting. The Counting adds it and asks how much of it you have seen, then you can rate it.</div>' : "") + '<div class="searchbar"><input id="q" type="search" placeholder="Search for a show" aria-label="Search for a show" value="' + esc(S.search.q) + '" autocomplete="off"></div><div id="results"></div>';
}
function renderResults() {
  const box = $("#results"); if (!box) return;
  const r = S.search;
  if (r.err) { box.innerHTML = '<div class="err">' + esc(r.err) + "</div>"; return; }
  if (r.results == null) { box.innerHTML = '<div class="empty">Type at least two letters to search.</div>'; return; }
  if (!r.results.length) { box.innerHTML = '<div class="empty">No shows found for "' + esc(r.q) + '". Try a different spelling.</div>'; return; }
  box.innerHTML = '<div class="grid">' + r.results.map(x => '<article class="card">' + poster({ id: x.id, name: x.name, poster_path: x.poster_path }) + '<div class="body"><h3>' + esc(x.name) + (x.year ? ' <span class="meta">(' + x.year + ")</span>" : "") + '</h3><p class="sub">' + esc(x.overview.length > 220 ? x.overview.slice(0, 220) + "..." : x.overview) + '</p><div class="row" style="margin-top:.5rem">' +
    (x.in_library ? '<span class="badge acc">In your library</span><button class="btn sm" data-a="open" data-id="' + x.id + '">Open</button>'
      : '<button class="btn ' + (S.search.seen ? "pri" : "") + ' sm" data-a="addseen" data-id="' + x.id + '">I have already watched it</button><button class="btn ' + (S.search.seen ? "" : "pri") + ' sm" data-a="addshow" data-id="' + x.id + '" data-st="plan">Add to watch list</button><button class="btn sm" data-a="addshow" data-id="' + x.id + '" data-st="watching">I am watching this</button>') + "</div></div></article>").join("") + "</div>";
}
function tog(a, on, label) { return '<div class="switch"><span>' + label + '</span><button class="tog" role="switch" aria-checked="' + on + '" aria-label="' + label + '" data-a="' + a + '"></button></div>'; }
function stlink(st) { return { unlocked: st }; }
function seasonSquares(sh) {
  const nx = sh.next;
  return '<div class="seasq" aria-label="Episodes, one square each">' + sh.season_list.map(se => '<div class="r"><b>S' + se.number + '</b><div class="sq">' + se.episodes.map(x => {
    const cls = x.watched > 0 ? "on" : nx && nx.id === x.id ? "next" : !x.aired ? "un" : "";
    return '<button class="sqi ' + cls + '" data-a="sqgo" data-id="' + se.number + "|" + x.id + '" aria-label="' + esc(x.label) + (x.watched > 0 ? ", watched" : !x.aired ? ", not aired yet" : nx && nx.id === x.id ? ", next to watch" : ", not watched") + '" title="' + esc(x.label) + '"></button>';
  }).join("") + "</div></div>").join("") + "</div>";
}
function fold(key, title, body, openByDefault) {
  const open = key in S.fold ? S.fold[key] : !!openByDefault;
  return '<section class="panel fold"><button class="foldh" aria-expanded="' + open + '" data-a="fold" data-id="' + key + '"><h3>' + title + '</h3><i aria-hidden="true"></i></button>' + (open ? '<div class="foldb">' + body + "</div>" : "") + "</section>";
}
function vShow() {
  const sh = S.show; if (!sh) return '<div class="spin">Loading...</div>';
  const p = sh.progress, o = sh.overrides, nx = sh.next, rd = sh.readiness;
  const labels = { plan: "Plan to watch", watching: "Watching", hold: "On hold", dropped: "Dropped", completed: "Completed" };
  // artwork leads: the landscape backdrop if there is one, otherwise the poster, enlarged, blurred and faded
  const art = sh.backdrop_path ? "/img/w1280" + sh.backdrop_path : sh.poster_path ? "/img/w780" + sh.poster_path : "";
  let h = '<button class="back" data-a="back">Back</button>';
  h += '<header class="showhero' + (sh.backdrop_path ? "" : " fromposter") + '" aria-hidden="true">' + (art ? '<img class="heroimg" alt="" src="' + art + '" onerror="this.remove()">' : "") + '<div class="herofade"></div></header>';
  h += '<div class="showtop">' + poster(sh, "xl") + '<div class="showhead"><h1>' + esc(sh.name) + '</h1><div class="row" style="margin:.5rem 0"><span class="badge ' + (rd.kind === "ready" ? "ready" : "") + '">' + esc(rd.text) + '</span><span class="badge">' + esc(sh.tmdb_status) + "</span>" + (sh.state ? '<span class="badge acc">' + sh.state + "</span>" : "") + '<span class="meta">' + esc(sh.genres.join(", ")) + (sh.networks.length ? ". " + esc(sh.networks.join(", ")) : "") + "</span></div></div>" +
    '<div class="showrest"><p class="sub overview' + (S.fold.overview ? " full" : "") + '">' + esc(sh.overview) + "</p>" + (sh.overview.length > 220 ? '<button class="btn quiet" data-a="fold" data-id="overview">' + (S.fold.overview ? "Show less" : "Read more") + "</button>" : "") +
    '<div class="row actions"><label class="meta" for="stsel">Status</label><select id="stsel" data-c="status"' + (sh.status ? "" : " disabled") + ">" + Object.keys(labels).map(k => '<option value="' + k + '"' + (sh.status === k ? " selected" : "") + ">" + labels[k] + "</option>").join("") + "</select>" + (nx ? '<button class="btn pri" data-a="mark" data-id="' + nx.id + '">Mark ' + esc(nx.label) + " watched</button>" : "") + "</div>" +
    '<div class="showprog"><div class="meta">' + p.watched + " of " + p.total + " aired episodes watched. Specials are " + (o.include_specials ? "counted" : "not counted") + ".</div>" + seasonSquares(sh) + "</div></div></div>";
  h += tipBox("show", TIPS_TEXT.show);
  h += '<div class="showcols"><section class="epcol">';
  sh.season_list.forEach(se => {
    const key = sh.id + ":" + se.number, open = key in S.open ? S.open[key] : (nx ? sh.next_season === se.number : se.number === sh.season_list[0].number);
    h += '<section class="season"><button class="sh" aria-expanded="' + open + '" data-a="tseason" data-id="' + key + '"><span>Season ' + se.number + seasonBadges(sh, se.number) + '</span><span class="meta">' + se.watched + " / " + se.total + (se.airing ? " (airing)" : "") + "</span></button>";
    if (open) h += se.episodes.map(x => epRow(x, nx && nx.id)).join("");
    h += "</section>";
  });
  if (sh.specials.length) {
    const key = sh.id + ":sp", open = S.open[key];
    h += '<section class="season"><button class="sh" aria-expanded="' + !!open + '" data-a="tseason" data-id="' + key + '"><span>Specials</span><span class="meta">Own silo' + (o.include_specials ? "" : ", not counted in progress") + "</span></button>";
    if (open) h += sh.specials.map(x => '<div class="ep" style="grid-template-columns:1fr auto"><div class="t"><small>' + esc(x.label) + "</small>" + epTitle(x) + (x.watched > 1 ? ' <span class="badge">Watched x' + x.watched + "</span>" : "") + '</div>' + (x.aired ? '<button class="check" aria-pressed="' + (x.watched > 0) + '" aria-label="Mark ' + esc(x.name || x.label) + ' watched" data-a="mark" data-id="' + x.id + '">' + (x.watched > 0 ? "&#10003;" : "") + "</button>" : '<span class="meta">Not aired</span>') + "</div>").join("");
    h += "</section>";
  }
  h += '</section><aside class="sidecol">' + ratingPanel(sh) +
    fold("rules", "Display rules for this show", tog("ttl", o.hide_titles, "Hide episode titles") + tog("abs", o.absolute_numbering, "Show absolute numbering (#17 style)") + tog("incsp", o.include_specials, "Count specials in progress") + '<p class="meta" style="margin-top:.4rem">These are stored as overrides. Your watch history is never touched by them.</p>', false) +
    (sh.cast.length ? fold("cast", "Main cast", '<div class="row">' + sh.cast.slice(0, 8).map(c => '<span class="badge">' + esc(c.name) + (S.castCounts && c.episodes ? " (" + c.episodes + " episodes)" : "") + "</span>").join("") + '</div><p class="meta" style="margin-top:.5rem">Episode counts are hidden because they can hint at who survives. <button class="btn quiet" data-a="castcount">' + (S.castCounts ? "Hide counts" : "Show counts") + "</button></p>", false) : "") +
    '<div class="row" style="margin-top:.4rem"><button class="btn sm" data-a="refresh">Refresh from TMDB</button><button class="btn sm" data-a="remove">Remove from my library</button></div><p class="meta" style="margin-top:.4rem">Removing a show keeps your watch history, so adding it again brings your progress back.</p></aside></div>';
  return h;
}
function epRow(x, nextId) {
  const watched = x.watched > 0;
  let still;
  if (!x.unlocked) still = '<div class="still lock" aria-hidden="true">Hidden</div>';
  else still = '<div class="still" data-k="' + (mix(x.id) % 4) + '" aria-hidden="true">' + (x.still_path ? '<img loading="lazy" alt="" src="/img/w300' + x.still_path + '" onerror="this.remove()">' : "") + "</div>";
  let syn = "";
  if (!x.unlocked) syn = '<div class="locked">Thumbnail and synopsis stay hidden until you finish the previous episode.</div>';
  else if (x.overview) {
    const open = !!S.revealed[x.id];
    syn = '<div class="syn"><button class="reveal" data-a="syn" data-id="' + x.id + '" aria-expanded="' + open + '" aria-controls="syn-' + x.id + '"><i aria-hidden="true"></i>' + (open ? "Hide synopsis" : "Reveal synopsis") + "</button>" +
      (open ? '<div class="synbox" id="syn-' + x.id + '">' + esc(x.overview) + "</div>" : "") + "</div>";
  }
  const acts = x.aired ? '<button class="check" aria-pressed="' + watched + '" aria-label="' + (watched ? "Watched, tap to review " : "Mark watched ") + esc(x.label) + '" data-a="mark" data-id="' + x.id + '">' + (watched ? "&#10003;" : "") + '</button><button class="btn quiet" data-a="upto" data-id="' + x.id + '">Seen up to here</button>' + (watched ? '<button class="btn quiet" data-a="fav" data-id="' + x.id + '" aria-pressed="' + !!x.favourite + '">' + (x.favourite ? "&#9829; Favourited" : "&#9825; Favourite") + "</button>" : "") : '<span class="meta">' + (x.air_date ? "Airs " + esc(x.air_date) : "Air date unknown") + "</span>";
  return '<div class="ep' + (x.id === nextId ? " nextrow" : "") + '" id="ep-' + x.id + '">' + still + '<div><div class="t"><small>' + esc(x.label) + "</small>" + epTitle(x) + (x.watched > 1 ? ' <span class="badge">Watched x' + x.watched + "</span>" : "") + "</div>" + syn + '</div><div class="acts">' + acts + "</div></div>";
}
function bars(rows, fmt, top) {
  if (!rows.length) return '<p class="meta">Nothing to show yet.</p>';
  const m = top || Math.max(...rows.map(r => r[1]), 1);  // top: draw against a fixed scale (ratings) instead of the biggest bar
  return rows.map(([k, v]) => '<div class="b"><span>' + esc(k) + '</span><div class="bar"><i style="width:' + v / m * 100 + '%"></i></div><span class="meta">' + fmt(v) + "</span></div>").join("");
}
function seasonTrendPanel(t) {
  if (!t || !t.shows) return "";
  const rows = [["Got better", t.improved], ["Held steady", t.held], ["Got worse", t.declined]];
  return '<div class="panel bars"><h3>How your shows age</h3>' + bars(rows, v => v + (v === 1 ? " show" : " shows")) +
    '<h3 style="margin:1rem 0 .5rem;font-size:.95rem">Average score by season number</h3>' + bars(t.by_number.map(([n, v, c]) => ["Season " + n + " (" + c + (c === 1 ? " show" : " shows") + ")", v]), v => v + " / " + t.scale, t.scale) +
    '<p class="meta" style="margin-top:.5rem">Across ' + t.shows + " show" + (t.shows === 1 ? "" : "s") + " where you scored at least two seasons. Got better or worse means the latest scored season against the first, by at least a point on a five-point scale.</p></div>";
}
function vStats() {
  const s = S.stats; if (!s) return '<div class="spin">Loading...</div>';
  const tip = tipBox("stats", TIPS_TEXT.stats);
  const mo = s.by_month.map(([k, v]) => { const [y, m] = k.split("-"); return [new Date(+y, +m - 1).toLocaleString(undefined, { month: "short", year: "2-digit" }), v]; });
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((n, i) => [n, s.by_weekday[i]]);
  const hrs = v => v + " h";
  const panel = (title, body, note) => '<div class="panel bars"><h3>' + title + "</h3>" + body + (note ? '<p class="meta" style="margin-top:.5rem">' + note + "</p>" : "") + "</div>";
  return '<div class="head"><div><h1>Stats</h1><p class="sub">Everything here is worked out from your watch log, your ratings and what TMDB knows about each show.</p></div></div>' + tip + '<div class="kpis"><div class="kpi"><b>' + s.episodes + '</b>episodes watched</div><div class="kpi"><b>' + Math.round(s.hours) + '</b>hours of TV</div><div class="kpi"><b>' + s.rewatched + '</b>rewatched episodes</div><div class="kpi"><b>' + s.completed + '</b>shows completed</div></div>' +
'<div class="statgrid">' +     panel("Where you watch", bars(s.by_network, hrs), "Hours by network or streaming service. A show on more than one network counts toward each.") +
    panel("How you rate, by genre", bars(s.rating_by_genre.map(([g, v, n]) => [g + " (" + n + (n === 1 ? " show" : " shows") + ")", v]), v => v + " / " + s.rating_max, s.rating_max), s.rated_shows ? "Your average final score for the shows you rated in each genre." : "Rate a show to see this.") +
    panel("Hours by decade", bars(s.by_decade, hrs), "The decade each show first aired.") +
    panel("Hours by genre", bars(s.by_genre, hrs), "A show counts toward each of its genres.") +
    panel("When you watch", bars(days, v => v), "Episodes you marked, by day of the week.") +
    panel("Episodes by month", bars(mo, v => v), s.undated + " bulk-marked episodes have no date, so they count toward progress and hours but not the day and month charts.") +
    seasonTrendPanel(s.season_trends) +
    panel("Most watched shows", bars(s.top_shows, hrs)) + "</div>";
}
function vLog() {
  const ev = S.log; if (!ev) return '<div class="spin">Loading...</div>';
  return '<div class="head"><div><h1>Watch log</h1><p class="sub">Every mark is recorded here and never deleted. Undoing a mark adds an undo entry. Bulk marks have no date.</p></div></div><div class="panel tablewrap"><table><thead><tr><th>#</th><th>Date</th><th>Type</th><th>Source</th><th>Show</th><th>Episode</th></tr></thead><tbody>' +
    (ev.length ? ev.map(e => "<tr><td>" + e.n + "</td><td>" + (e.ts ? new Date(e.ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "-") + "</td><td>" + e.type + "</td><td>" + e.source + "</td><td>" + esc(e.show) + "</td><td>" + esc(e.label) + "</td></tr>").join("") : '<tr><td colspan="6" class="meta">No episodes marked yet.</td></tr>') + "</tbody></table></div>";
}
function vData() {
  const b = S.backups; if (!b) return '<div class="spin">Loading...</div>';
  return '<div class="head"><div><h1>Backups and data</h1><p class="sub">The Counting saves a copy of your data when it opens and when it closes after changes, and keeps the newest ' + S.app.backup_keep + ".</p></div></div>" +
    '<div class="twocol">' + '<div class="panel"><h3>Backups</h3><p class="meta">Folder: ' + esc(b.folder) + '</p><div class="row" style="margin:.6rem 0"><button class="btn pri sm" data-a="backupnow">Back up now</button><button class="btn sm" data-a="openbackups">Open folder</button></div>' +
    (b.backups.length ? b.backups.map(x => '<div class="backup-row"><div><b>' + when(x.modified) + '</b> <span class="meta">' + kb(x.size) + " - " + esc(x.name) + '</span></div><button class="btn sm" data-a="restore" data-id="' + esc(x.name) + '">Restore</button></div>').join("") : '<p class="meta">No backups yet. Add a show and mark an episode, and one is made automatically.</p>') + "</div>" +
    '<div class="panel"><h3>Export and import</h3><p class="meta">An export is a plain file with your lists and watch history. It works even if you move to another computer. Show details are fetched again from TMDB after an import.</p><div class="row" style="margin-top:.6rem"><button class="btn sm" data-a="export">Export my data</button><button class="btn sm" data-a="importpick">Import from a file</button><input id="importfile" type="file" accept=".json,application/json" hidden></div></div>' + '</div>';
}
function selfBox() {
  const r = S.self; if (!r) return "";
  if (r.busy) return '<p class="meta" style="margin-top:.6rem">Checking...</p>';
  if (r.err) return '<div class="err" style="margin-top:.6rem">' + esc(r.err) + "</div>";
  return '<textarea class="selfout" readonly rows="14" aria-label="Self-check result">' + esc(r.text) + '</textarea><div class="row" style="margin-top:.4rem"><button class="btn sm" data-a="selfcopy">Copy</button><span class="meta">' + (r.ok ? "Everything required passed." : "Something needs attention. Please send this text.") + "</span></div>";
}
function lanPanel() {
  const l = S.lan; if (!l) return "";
  let h = '<div class="panel"><h3>Use on my phone</h3><div class="switch"><span>Let phones on my home Wi-Fi open The Counting<br><span class="meta">Off unless you turn it on. Every phone has to be paired first.</span></span><button class="tog" role="switch" aria-checked="' + l.enabled + '" aria-label="Use on my phone" data-a="lanon"></button></div>';
  if (l.error) h += '<div class="err" style="margin-top:.6rem">' + esc(l.error) + "</div>";
  if (l.running) {
    h += '<p class="meta" style="margin:.6rem 0">Listening at <b>' + esc((l.urls[0] || "this computer")) + '</b>. The computer must be on, awake and on the same Wi-Fi as the phone.</p><div class="row"><button class="btn pri sm" data-a="lanpair">Pair a phone</button></div>';
    h += l.devices.length ? '<h3 style="margin:1rem 0 .3rem;font-size:.95rem">Paired devices</h3>' + l.devices.map(d => '<div class="backup-row"><div><b>' + esc(d.name) + '</b> <span class="meta">last used ' + when(d.last_seen) + '</span></div><button class="btn sm" data-a="lanforget" data-id="' + d.id + '">Forget</button></div>').join("") : '<p class="meta" style="margin-top:.8rem">No phones paired yet.</p>';
  }
  h += '<p class="meta" style="margin-top:.8rem">This uses plain HTTP, which is fine on your own home network but not on public Wi-Fi. A paired phone can track, rate and browse, but cannot open folders, make backups, export, or change your TMDB key. Windows may ask whether to allow network access the first time. Choose private networks only.</p></div>';
  return h;
}
function pairModal() {
  const p = S.pair; if (!p) return "";
  const url = p.links[0] || "";
  let svg = "";
  try { const q = qrcode(0, "M"); q.addData(url); q.make(); svg = q.createSvgTag({ cellSize: 5, margin: 0, scalable: true }); } catch (e) { svg = ""; }
  return "<h2>Pair a phone</h2><ol style=\"padding-left:1.2rem;margin:.4rem 0\"><li>Connect the phone to the same Wi-Fi as this computer.</li><li>Scan this code with the phone's camera and open the link.</li></ol>" +
    '<div class="qrbox" role="img" aria-label="QR code for pairing">' + svg + '</div><p class="meta">Can\'t scan? On the phone open <b>' + esc(p.addresses[0] || "") + '</b> and type this code:</p><div class="pin" aria-label="Pairing code">' + esc(p.pin) + '</div><p class="meta">The code works once and expires in ' + Math.round(p.expires_in / 60) + ' minutes. Pair in your browser first, then use <b>Add to Home Screen</b> to keep The Counting on the phone like an app. On an iPhone, use Safari, and pair <b>before</b> adding it: the icon copies the pairing once, at that moment.</p><div class="stack">' + btn("close", "", "Done", "pri") + "</div>";
}
function vSettings() {
  const a = S.app, remote = a.remote;
  return '<div class="head"><div><h1>Settings</h1></div></div>' + (S.settingsErr ? '<div class="err">' + esc(S.settingsErr) + "</div>" : "") +
    '<div class="twocol">' + (remote ? "" : lanPanel()) + '<div class="panel"><h3>Appearance</h3><div class="seg" role="group" aria-label="Colour mode">' + [["system", "Match my device"], ["light", "Light"], ["dark", "Dark"]].map(m => '<button aria-pressed="' + (a.theme === m[0]) + '" data-a="settheme" data-id="' + m[0] + '">' + m[1] + "</button>").join("") + '</div><p class="meta" style="margin-top:.5rem">The button at the top right also switches between light and dark.' + (remote ? " On a phone this choice applies to this phone only." : "") + "</p></div>" +
    (remote ? '<div class="panel"><h3>This phone</h3><p class="meta">You are using The Counting on this phone through your computer. Keys, backups and exports are managed on the computer.</p><div class="row" style="margin-top:.6rem"><button class="btn sm" data-a="tourreplay">Show the tour again</button><button class="btn sm" data-a="guidereset">Bring back tips and the checklist</button></div></div>' :
      '<div class="panel"><h3>TMDB API key</h3><p class="meta">' + (a.has_key ? "A key is saved on this computer." : "No key saved yet.") + ' You can get or manage keys at <button class="link" data-a="tmdb-api">themoviedb.org</button>.</p><div class="field"><label for="key">Paste a new key to replace it</label><input id="key" type="password" autocomplete="off" spellcheck="false"></div><button class="btn pri sm" data-a="savekey">Save key</button></div>' +
      '<div class="panel"><h3>Connection</h3><div class="switch"><span>Use secure DNS if needed<br><span class="meta">If the normal connection to TMDB fails, The Counting asks Cloudflare or Google DNS for TMDB\'s address, like a browser with secure DNS does. Nothing else is sent.</span></span><button class="tog" role="switch" aria-checked="' + a.secure_dns + '" aria-label="Use secure DNS if needed" data-a="securedns"></button></div><h3 style="margin-top:1rem">Connection check</h3><p class="meta">If The Counting cannot reach TMDB, this shows which step fails.</p><div style="margin-top:.6rem"><button class="btn sm" data-a="diagnose">Run check</button></div><div id="diag"></div></div>' +
      '<div class="panel"><h3>Backups</h3><div class="field"><label for="bfolder">Backup folder</label><div class="row"><input id="bfolder" type="text" value="' + esc(a.backup_folder) + '" style="flex:1;min-width:220px;background:var(--surf);border:1px solid var(--line);border-radius:8px;padding:.6rem .75rem"><button class="btn sm" data-a="browse">Browse</button></div><span class="meta">Point this at a cloud-synced folder if you want copies stored off this computer.</span></div><div class="field"><label for="bkeep">Backups to keep</label><input id="bkeep" type="number" min="3" max="100" value="' + a.backup_keep + '" style="max-width:120px"></div><button class="btn pri sm" data-a="savebackup">Save backup settings</button></div>' +
      '<div class="panel"><h3>Help</h3><p class="meta">The Counting keeps a log of what it does and any errors. If something goes wrong, the file <b>thecounting.log</b> in this folder shows why.</p><div style="margin-top:.6rem"><button class="btn sm" data-a="opendata">Open The Counting\'s data folder</button></div><h3 style="margin-top:1rem;font-size:.95rem">Self-check</h3><p class="meta">Checks that this copy of The Counting has everything it needs: its files, database, secure connections and window. It does not touch your shows. Useful if something does not work, or to send me when testing on a new computer.</p><div style="margin-top:.6rem"><button class="btn sm" data-a="selftest">Run a self-check</button></div>' + selfBox() + '<h3 style="margin-top:1rem;font-size:.95rem">Guide</h3><p class="meta">Replay the tour, or bring back the one-time tips and the Getting started list.</p><div class="row" style="margin-top:.6rem"><button class="btn sm" data-a="tourreplay">Show the tour again</button><button class="btn sm" data-a="guidereset">Bring back tips and the checklist</button></div></div>') + '</div>';
}

/* ---------- first-time guide ---------- */
const GUIDE_KEY = "tc-guide";
async function guideLoad() {
  let srv; try { srv = await api("/api/guide"); } catch (e) { return; }
  let state = srv.state;
  if (S.app.remote) {   // a phone keeps its own copy in the browser and never changes the computer's
    let mine = null; try { mine = JSON.parse(localStorage.getItem(GUIDE_KEY)); } catch (e) { /* none yet */ }
    state = mine || (srv.existing ? { tour: "skipped", checklist: "dismissed", tips: srv.tips.slice(), visited: ["arena", "discover"] } : { tour: "", checklist: "", tips: [], visited: [] });
  }
  S.guide = { state, progress: srv.progress, tips: srv.tips };
  if (S.app.remote) guideKeep();
}
function guideKeep() { try { localStorage.setItem(GUIDE_KEY, JSON.stringify(S.guide.state)); } catch (e) { /* private mode */ } }
async function guideSave(patch) {
  const g = S.guide; if (!g) return;
  if (S.app.remote) {
    const s = g.state;
    if (patch.reset) g.state = { tour: "", checklist: "", tips: [], visited: [] };
    else {
      if ("tour" in patch) s.tour = patch.tour;
      if ("checklist" in patch) s.checklist = patch.checklist;
      if (patch.tip && !s.tips.includes(patch.tip)) s.tips.push(patch.tip);
      if (patch.visit && !s.visited.includes(patch.visit)) s.visited.push(patch.visit);
    }
    return guideKeep();
  }
  try { const r = await api("/api/guide", "POST", patch); g.state = r.state; g.progress = r.progress; } catch (e) { /* guidance must never get in the way */ }
}
function guideVisit(name) { const g = S.guide; if (g && !g.state.visited.includes(name)) guideSave({ visit: name }); }
function guideProgress() { const g = S.guide; if (!g) return {}; return { ...g.progress, arena: g.state.visited.includes("arena"), discover: g.state.visited.includes("discover") }; }

function tipBox(id, html) {
  const g = S.guide; if (!g || g.state.tips.includes(id)) return "";
  return '<aside class="tip" role="note"><div><b>Tip.</b> ' + html + '</div><button class="btn sm" data-a="tipok" data-id="' + id + '">Got it</button></aside>';
}
const TIPS_TEXT = {
  ratings: "Rankings lists your shows by the score that counts. Use <b>Scorecard</b> to say what matters to you, rate shows from their show page, and use <b>Arena</b> to settle close calls.",
  arena: "The arena only asks about shows you scored 4 out of 5 or higher that are tied or close. Answer a round of five, or stop whenever you like.",
  discover: "Discover suggests shows from what you have finished and rated. Rate at least three shows and it ranks them for you, with the reason for each pick.",
  stats: "Stats are worked out from your watch log and ratings, so they fill in as you watch and rate.",
  show: "Each square is an episode. Click one to jump to it, use <b>Seen up to here</b> to mark everything before an episode, and press <b>Reveal synopsis</b> only when you are ready.",
};

const CHECK = [
  ["added", "Add your first show", "Search TMDB and add something you watch."],
  ["marked", "Mark an episode watched", "One tap on Mark watched."],
  ["rated", "Rate a show", "Open a show and press Rate this show."],
  ["favourite", "Favourite an episode", "Tap the heart on an episode you have watched."],
  ["arena", "Visit the arena", "Close calls between your favourites are settled here."],
  ["discover", "See your Discover list", "Suggestions ranked from your own ratings."],
  ["phone", "Use it on your phone", "Optional: pair a phone from Settings."],
];
function guideChecklist() {
  const g = S.guide; if (!g || g.state.checklist === "dismissed") return "";
  const p = guideProgress(), items = CHECK.filter(c => !(c[0] === "phone" && S.app.remote)), done = items.filter(c => p[c[0]]).length;
  if (done === items.length) return "";
  return '<section class="panel guide" aria-label="Getting started"><div class="row" style="justify-content:space-between"><h3>Getting started <span class="meta">' + done + " of " + items.length + ' done</span></h3><div class="row"><button class="btn quiet" data-a="tourstart">Take the tour</button><button class="btn quiet" data-a="chkhide">Hide</button></div></div><ul class="chk">' +
    items.map(c => '<li class="' + (p[c[0]] ? "done" : "") + '"><span class="tick" aria-hidden="true">' + (p[c[0]] ? "&#10003;" : "") + '</span><div><b>' + c[1] + '</b><div class="meta">' + c[2] + "</div></div>" + (p[c[0]] ? '<span class="meta">Done</span>' : '<button class="btn sm" data-a="chkgo" data-id="' + c[0] + '" aria-label="Show me: ' + c[1] + '">Show me</button>') + "</li>").join("") + "</ul></section>";
}
async function pulse(sel) {
  for (let i = 0; i < 30; i++) {
    const el = document.querySelector(sel);
    if (el) { if (el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("pulse"); setTimeout(() => el.classList.remove("pulse"), 5000); return true; }
    await new Promise(r => setTimeout(r, 100));
  }
  return false;
}
async function firstShowId() {
  for (const st of ["watching", "completed", "hold", "plan", "dropped"]) { const r = await api("/api/library?status=" + st); if (r.shows.length) return r.shows[0].id; }
  return null;
}
async function guideShowMe(id) {
  if (id === "added") { await go("search"); return pulse("#q"); }
  if (id === "marked") { await go("library"); if (!(await pulse('[data-a="mark"]'))) { await go("search"); return pulse("#q"); } return; }
  if (id === "rated" || id === "favourite") {
    const sid = await firstShowId();
    if (!sid) { await go("search"); toast("Add a show first."); return pulse("#q"); }
    await go("show", { showId: sid });
    if (id === "rated") return pulse('[data-a="rateshow"], [data-a="rateseasons"]');
    if (!(await pulse('[data-a="fav"]'))) toast("Mark an episode watched first, then a heart appears.");
    return;
  }
  if (id === "arena") { S.rt.tab = "arena"; return go("ratings"); }
  if (id === "discover") return go("discover");
  if (id === "phone") { await go("settings"); return pulse('[data-a="lanon"]'); }
}

/* The tour draws its pictures with the app's own components and sample data, so they always match the real thing. */
const DEMO = { id: 9001, name: "Harbour Lights", poster_path: null, tmdb_status: "Returning Series", seasons: 2, episodes: 8, progress: { watched: 5, total: 6 }, next: { id: 9002, label: "S1E6", name: "The Tide Turns" }, rating: null, state: null, loading: false };
const demo = html => '<div class="demo" inert aria-hidden="true">' + html.replace(/ data-a="[^"]*"/g, "").replace(/ data-id="[^"]*"/g, "") + "</div>";
function tourSteps() {
  const remote = S.app && S.app.remote;
  const ep = (id, label, name, unlocked) => epRow({ id, label, name, overview: "A short synopsis.", unlocked, aired: true, watched: 0, still_path: null }, null);
  return [
    { title: "Welcome to The Counting", text: "A private place to keep track of the TV you watch. Everything lives on your own computer, with no account and no ads. Here is a two-minute look around, and you can skip it at any time.",
      art: () => '<svg viewBox="0 0 150 52" width="220" aria-hidden="true"><polygon points="3,49 25,5 47,49" fill="var(--yellow)" stroke="var(--ink)" stroke-width="3"/><rect x="58" y="10" width="38" height="38" fill="var(--red)" stroke="var(--ink)" stroke-width="3"/><circle cx="125" cy="29" r="19" fill="var(--blue)" stroke="var(--ink)" stroke-width="3"/></svg>' },
    { title: "One square for every episode", text: "In your Library each square is an episode. Teal means watched, a red outline is the one to watch next, and hatched squares have not aired yet. Press Mark watched to log the next one.",
      art: () => demo(libCard(DEMO)) + demo('<div class="row"><span class="sq lg"><i class="on"></i></span><span class="meta">Watched</span><span class="sq lg"><i class="next"></i></span><span class="meta">Next</span><span class="sq lg"><i class="un"></i></span><span class="meta">Not aired</span></div>') },
    { title: "Add the shows you watch", text: "Search TMDB, then add a show to your watch list, start tracking it, or record one you have already watched. Shows that have finished airing are marked Ready to binge.",
      art: () => demo('<div class="row"><span class="btn pri sm">I am watching this</span><span class="btn sm">Add to watch list</span><span class="btn sm">I have already watched it</span></div><div class="row"><span class="badge ready">Ready to binge</span><span class="badge">Still airing (6 of 8 episodes out)</span><span class="badge acc">Up to date</span></div>') },
    { title: "No spoilers", text: "Thumbnails and synopses stay hidden until you have watched the episode before, and even then a synopsis stays tucked away until you press Reveal. You can hide episode titles too, in a show's display rules.",
      art: () => demo('<div style="width:100%">' + ep(9101, "S1E6", "The Tide Turns", true) + ep(9102, "S1E7", "Hidden until you are ready", false) + "</div>") },
    { title: "Rate shows your way", text: "Say once what matters to you (writing, acting, cinematography, editing, sound, direction), then rate shows quickly. Rate seasons too, and choose whether season scores change the show's score. Your best and weakest seasons are marked.",
      art: () => demo('<div class="final" style="margin:0">4 / 5</div><div class="row"><span class="badge">Writing 5/5</span><span class="badge">Acting 4/5</span><span class="badge">Cinematography 5/5</span><span class="badge">Sound 3/5</span></div><div class="row"><span class="badge ready">Season 1 5 / 5, best</span><span class="badge warn">Season 2 3 / 5, weakest</span></div>') },
    { title: "Rankings and the arena", text: "Rankings list your shows by the score that counts. When two of your favourites are tied or close, the arena asks which is better, five questions at a time, and you can stop whenever you like.",
      art: () => demo('<div class="vs" style="width:100%"><div class="vsc">' + poster({ id: 9201, name: "Harbour Lights", poster_path: null }) + '<b style="display:block;margin-top:.4rem">Harbour Lights</b><span class="meta">4.5 / 5</span></div><div class="vsc">' + poster({ id: 9202, name: "Night Ferry", poster_path: null }) + '<b style="display:block;margin-top:.4rem">Night Ferry</b><span class="meta">4.5 / 5</span></div></div><span class="btn pri">Which is better?</span>') },
    { title: "Discover and stats", text: "Rate three shows and Discover ranks suggestions for you, with the reason for each. Stats show your hours by network, decade and genre, how you rate each genre, and how your shows age.",
      art: () => demo('<div style="width:100%"><span class="badge ready">Strong match</span><div class="why" style="margin:.4rem 0"><b>Why here:</b> It matches the dramas you rated highest.</div>' + bars([["Drama", 45], ["Mystery", 18], ["Comedy", 6]], v => v + " h") + "</div>") },
    { title: remote ? "On your phone" : "Your data, and your phone", text: remote ? "You are using The Counting on this phone through your computer, which must stay on. Use your browser's Add to Home Screen to keep it like an app. Backups and exports are managed on the computer."
      : "The Counting backs up automatically, and you can export everything. In Settings, Use on my phone lets a phone on your Wi-Fi use it too. You can take this tour again any time from the Profile menu.",
      art: () => demo('<div class="row"><span class="badge">Backups: automatic</span><span class="badge">Export: any time</span><span class="badge">Phone: optional</span></div>') },
  ];
}
function tourModal() {
  const t = S.tour; if (!t) return "";
  const steps = tourSteps(), i = t.i, st = steps[i];
  return '<div class="tour"><div class="meta">Step ' + (i + 1) + " of " + steps.length + '</div><div class="stage">' + st.art() + "</div><h2>" + esc(st.title) + '</h2><p class="sub">' + esc(st.text) + '</p><div class="dots" aria-hidden="true">' + steps.map((_, k) => '<i class="' + (k === i ? "on" : k < i ? "past" : "") + '"></i>').join("") + '</div><div class="row tourbtns">' + (i > 0 ? btn("tourback", "", "Back") : "") + '<span style="flex:1"></span>' + btn("tourskip", "", i < steps.length - 1 ? "Skip tour" : "Close", "quiet") + (i < steps.length - 1 ? btn("tournext", "", "Next", "pri") : btn("tourdone", "", "Finish", "pri")) + "</div></div>";
}
const offerModal = () => '<h2>Welcome to The Counting</h2><p class="sub">Would you like a two-minute tour of what it can do? You can find it again any time in the Profile menu.</p><div class="stack">' + btn("tourstart", "", "Show me around", "pri") + btn("tourskip", "", "Not now", "quiet") + "</div>";
function maybeOfferTour() { const g = S.guide; if (!g || !S.app.has_key || g.state.tour !== "" || S.modal) return; S.offer = true; S.modal = offerModal(); render(); }

/* ---------- modals ---------- */
const btn = (a, id, t, c, extra) => '<button class="btn ' + (c || "") + '" data-a="' + a + '" data-id="' + esc(id) + '"' + (extra || "") + ">" + t + "</button>";
const mRewatch = id => '<h2>You have already watched this episode</h2><p class="sub">Is this a rewatch, or did a tap go wrong?</p><div class="stack">' + btn("resolve", id, "Yes, I am rewatching it", "pri", ' data-r="rewatch"') + btn("close", "", "No, that was a mistake") + btn("resolve", id, "My earlier mark was wrong, remove it", "", ' data-r="undo"') + "</div>";
const mGaps = (id, n) => "<h2>Mark the earlier episodes too?</h2><p class=\"sub\">" + n + " earlier aired episode" + (n > 1 ? "s are" : " is") + " not marked. Episodes you already watched are left alone.</p><div class=\"stack\">" + btn("resolve", id, "Mark all " + n + " before it too", "pri", ' data-r="all"') + btn("resolve", id, "Just this one", "", ' data-r="one"') + btn("close", "", "Cancel", "quiet") + "</div>";
const mConfirm = (title, text, action, id, label) => "<h2>" + esc(title) + '</h2><p class="sub">' + esc(text) + '</p><div class="stack">' + btn(action, id, label, "pri") + btn("close", "", "Cancel", "quiet") + "</div>";


/* ---------- ratings, arena, discover ---------- */
const scoreText = (f, max) => (Math.round(f * max * 10) / 10) + " / " + max;
const fmtDate = t => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
function draftFinal(d) {
  const p = d.p;
  if (d.mode !== "card") return d.o / (d.mode === "10" ? 10 : 5);
  const tw = p.criteria.reduce((a, c) => a + c.weight, 0);
  return tw ? p.criteria.reduce((a, c) => a + c.weight * d.s[c.key] / 5, 0) / tw : p.criteria.reduce((a, c) => a + d.s[c.key] / 5, 0) / p.criteria.length;
}
function ratingPanel(sh) {
  const ri = sh.rating_info, cur = ri.current, p = sh.rating_profile;
  const favs = sh.season_list.flatMap(se => se.episodes).filter(e => e.favourite);
  let h = '<div class="panel"><h3>Your rating</h3>';
  if (cur) {
    h += '<div class="row" style="justify-content:space-between"><div><div class="final" style="margin:0">' + esc(cur.final) + '</div><span class="meta">' + (cur.mode === "card" ? "Weighted from your scorecard" : "Simple rating") + " on " + fmtDate(cur.created_at) + '</span></div><button class="btn" data-a="rateshow" data-id="' + sh.id + '">Edit rating</button></div>';
    if (cur.scores) h += '<div class="row" style="margin-top:.6rem">' + p.criteria.map(c => '<span class="badge">' + esc(c.name) + " " + cur.scores[c.key] + "/5</span>").join("") + (cur.gut != null ? '<span class="badge ready">Gut ' + cur.gut + "/5</span>" : "") + "</div>";
    if (ri.history.length) h += '<details style="margin-top:.7rem"><summary class="meta" style="cursor:pointer">Earlier ratings (' + ri.history.length + ')</summary>' + ri.history.map(x => '<div class="backup-row"><span>' + esc(x.final) + '</span><span class="meta">' + fmtDate(x.created_at) + "</span></div>").join("") + "</details>";
  } else {
    const sr = sh.season_rating;
    if (sr && sr.counts_toward_show && sr.effective_text) h += '<div class="final" style="margin:0">' + esc(sr.effective_text) + '</div><span class="meta">Worked out from your season scores</span><div style="margin-top:.6rem"><button class="btn" data-a="rateshow" data-id="' + sh.id + '">Also rate the show itself</button></div>';
    else h += '<p class="sub">Not rated yet.</p><div style="margin-top:.6rem"><button class="btn pri" data-a="rateshow" data-id="' + sh.id + '">Rate this show</button></div>';
  }
  h += seasonsSection(sh);
  h += '<h3 style="margin:1rem 0 .4rem">Favourite episodes</h3>' + (favs.length ? '<div class="row">' + favs.map(x => '<span class="badge">&#9829; ' + esc(x.label) + (x.name ? " " + esc(x.name) : "") + "</span>").join("") + "</div>" : '<p class="meta">Tap the heart on a watched episode to favourite it.</p>');
  return h + "</div>";
}
function seasonBadges(sh, n) {
  const sr = sh.season_rating; if (!sr || !sr.multi) return "";
  const x = sr.seasons.find(e => e.season === n); if (!x || x.score == null) return "";
  return ' <span class="badge">' + esc(x.text) + "</span>" + (x.best ? ' <span class="badge ready">Best season</span>' : "") + (x.weakest ? ' <span class="badge warn">Weakest</span>' : "");
}
function seasonsSection(sh) {
  const sr = sh.season_rating; if (!sr || !sr.multi) return "";
  const modeText = { off: "Season scores are for your own interest and do not change this show's score.", blend: "Season scores count for " + sr.mix + "% of this show's score.", seasons: "This show's score is worked out from its season scores alone." }[sr.mode];
  let h = '<h3 style="margin:1rem 0 .4rem">Seasons</h3>';
  if (!sr.rated) h += '<p class="meta">Rate each season to see which was best, and optionally let the scores count toward the show.</p>';
  else {
    h += '<div class="row">' + sr.seasons.filter(x => x.score != null).map(x => '<span class="badge' + (x.best ? " ready" : x.weakest ? " warn" : "") + '">Season ' + x.season + " " + esc(x.text) + (x.best ? ", best" : x.weakest ? ", weakest" : "") + "</span>").join("") + "</div>";
    h += '<p class="meta" style="margin-top:.4rem">' + esc(modeText) + (sr.counts_toward_show && sr.base_text ? " Show " + esc(sr.base_text) + ", seasons " + esc(sr.avg_text) + ", counts as " + esc(sr.effective_text) + "." : "") + "</p>";
  }
  return h + '<div style="margin-top:.6rem"><button class="btn sm" data-a="rateseasons" data-id="' + sh.id + '">' + (sr.rated ? "Edit season scores" : "Rate seasons") + "</button></div>";
}
function previewSeasons(d) {
  const sr = d.info, rated = d.rows.filter(r => d.scores[r.season] != null);
  if (!rated.length) return "Score at least one season to see the effect.";
  const w = rated.reduce((a, r) => a + Math.max(1, r.episodes), 0), avg = rated.reduce((a, r) => a + d.scores[r.season] / d.scale * Math.max(1, r.episodes), 0) / w;
  const txt = f => scoreText(f, d.scale), base = sr.base_fraction;
  const eff = d.mode === "off" ? base : d.mode === "seasons" || base == null ? avg : (1 - d.mix / 100) * base + d.mix / 100 * avg;
  return "Seasons average " + txt(avg) + (base != null ? "; the show itself " + txt(base) : "") + (d.mode === "off" ? ". The show's score stays " + (base != null ? txt(base) : "unrated") + "." : ". Counts as " + txt(eff) + ".");
}
function seasonModal() {
  const d = S.sdraft; if (!d) return "";
  if (d.step === "tie") {
    const pair = d.info.pending[0];
    if (!pair) return "";
    const [a, b] = pair, topText = d.info.seasons.find(x => x.season === a).text;
    return "<h2>Which season was better?</h2><p class=\"sub\">Season " + a + " and Season " + b + " both scored " + esc(topText) + ". Your answer decides which one is called your best season.</p><div class=\"stack\">" +
      btn("stie", a + "|" + b + "|a", "Season " + a + " was better", "pri") + btn("stie", a + "|" + b + "|b", "Season " + b + " was better", "pri") + btn("stie", a + "|" + b + "|same", "About the same") + btn("sdone", "", "Not now", "quiet") + "</div>";
  }
  const pick = r => '<div class="np" role="group" aria-label="Season ' + r.season + ' score">' + Array.from({ length: d.scale }, (_, i) => i + 1).map(v => '<button aria-pressed="' + (d.scores[r.season] === v) + '" data-a="spick" data-id="' + r.season + "|" + v + '">' + v + "</button>").join("") + "</div>";
  return "<h2>Rate the seasons of " + esc(d.name) + '</h2><p class="meta">Tap a score for each season you remember. Seasons you skip are left out. A score of ' + d.scale + " is the best.</p>" +
    '<div class="seasonrows">' + d.rows.map(r => '<div class="srow"><div><b>Season ' + r.season + '</b> <span class="meta">' + r.episodes + " episodes</span></div>" + pick(r) + "</div>").join("") + "</div>" +
    '<h3 style="margin:1rem 0 .4rem">Should these scores change the show\'s score?</h3><div class="seg" role="group" aria-label="How season scores count">' +
    [["off", "No"], ["blend", "Blend"], ["seasons", "Seasons only"]].map(m => '<button aria-pressed="' + (d.mode === m[0]) + '" data-a="smode" data-id="' + m[0] + '">' + m[1] + "</button>").join("") + "</div>" +
    (d.mode === "blend" ? '<div class="slider" style="grid-template-columns:7rem 1fr 3rem"><span>Seasons count for</span><input type="range" min="10" max="90" step="10" value="' + d.mix + '" data-s="mix" aria-label="How much the seasons count"><b id="mixv">' + d.mix + "%</b></div>" : "") +
    '<p class="meta" id="spreview" style="margin-top:.5rem">' + esc(previewSeasons(d)) + '</p><div class="stack">' + btn("ssave", "", "Save season scores", "pri") + btn("sdone", "", "Cancel", "quiet") + "</div>";
}
async function openSeasonModal(showId) {
  const sh = await api("/api/shows/" + showId), info = sh.season_rating;
  S.sdraft = { id: showId, name: sh.name, info, scale: info.scale, mode: info.mode, mix: info.mix, step: "scores",
    rows: info.seasons.map(x => ({ season: x.season, episodes: x.episodes })), scores: Object.fromEntries(info.seasons.map(x => [x.season, x.score])) };
  S.modal = seasonModal(); render();
}
function vDiscover() {
  const d = S.disc; if (!d) return '<div class="spin">Finding suggestions...</div>';
  const mode = d.mode;
  let h = '<div class="head"><div><h1>Discover</h1><p class="sub">Candidates come from TMDB. The ranking is ours, built from how you rated your own shows. Shows you already track or dismissed never appear here.</p></div></div>' +
    '<div class="chips" role="group" aria-label="Ranking"><button class="chip" aria-pressed="' + (mode === "you") + '" data-a="dmode" data-id="you"' + (d.unlocked ? "" : " disabled") + '>Ranked for you</button><button class="chip" aria-pressed="' + (mode === "tmdb") + '" data-a="dmode" data-id="tmdb">TMDB order</button></div>';
  if (!d.unlocked) h += '<div class="syncnote">Rate ' + d.need + ' shows to rank suggestions by your taste. You have rated ' + d.rated + ". Until then, suggestions use TMDB consensus from the shows you completed.</div>";
  if (mode === "you") h += '<details class="panel"><summary>How this is ranked</summary><p class="meta" style="margin-top:.5rem">TMDB tells us which shows are linked to the ones you rated. Those links only find candidates. The order comes from your ratings: a candidate ranks higher when the shows that point to it are ones you rated highly, with a small bonus for each extra link, plus a nudge from how you rate its genres. Change your importance settings or answer arena comparisons and the order changes with them. Suggestions are guesses from a small amount of data, so treat the order as a starting point.</p></details>';
  if (!d.cards.length) return h + '<div class="empty">' + (S.app.counts.completed || d.rated ? "No suggestions right now. Rate or complete more shows to get new ones." : "Suggestions start once you have completed or rated a show. Finish one, or add a show you have already watched.") + "</div>";
  return h + '<div class="grid">' + d.cards.map((c, i) => '<article class="card">' + poster(c) + '<div class="body"><div class="row" style="justify-content:space-between"><h3>' + (mode === "you" ? (i + 1) + ". " : "") + esc(c.name) + (c.year ? ' <span class="meta">(' + c.year + ")</span>" : "") + "</h3>" + (c.tier ? '<span class="badge ' + (c.tier === "Strong match" ? "ready" : "") + '">' + c.tier + "</span>" : "") + '</div><p class="sub">' + esc(c.overview.length > 200 ? c.overview.slice(0, 200) + "..." : c.overview) + "</p>" +
    (mode === "you" ? '<div class="why"><b>Why here:</b> ' + esc(c.why) + (c.vs_next ? "<br><b>Versus the next pick:</b> " + esc(c.vs_next) : "") + "</div>" : '<div class="meta" style="margin:.4rem 0">Recommended because you finished ' + esc(c.from.join(" and ")) + "." + (c.links > 1 ? " <b>Matches " + c.links + " of your shows.</b>" : "") + "</div>") +
    '<div class="meta" style="margin-bottom:.5rem">' + esc(c.genres.join(", ")) + '</div><div class="row"><button class="btn pri sm" data-a="dadd" data-id="' + c.id + '">Add to watch list</button><button class="btn sm" data-a="dseen" data-id="' + c.id + '">Already seen</button><button class="btn quiet" data-a="ddismiss" data-id="' + c.id + '">Not interested</button></div></div></article>').join("") + "</div>";
}
function vRatings() {
  const tabs = [["ranks", "Rankings"], ["card", "Scorecard"], ["arena", "Arena"], ["favs", "Favourites"]];
  const p = S.rt.profile; if (!p) return '<div class="spin">Loading...</div>';
  return '<div class="head"><div><h1>Ratings</h1><p class="sub">Say what matters to you once, rate shows quickly, and settle close calls in the arena.</p></div></div>' + tipBox("ratings", TIPS_TEXT.ratings) + (S.rt.tab === "arena" ? tipBox("arena", TIPS_TEXT.arena) : "") + '<div class="chips" role="group" aria-label="Ratings sections">' + tabs.map(t => '<button class="chip" aria-pressed="' + (S.rt.tab === t[0]) + '" data-a="rtab" data-id="' + t[0] + '">' + t[1] + "</button>").join("") + "</div>" + (S.rt.tab === "card" ? '<div class="twocol">' + rCard() + "</div>" : '<div class="narrow">' + ({ ranks: rRanks, arena: rArena, favs: rFavs })[S.rt.tab]() + "</div>");
}
function rCard() {
  const p = S.rt.profile, modes = [["card", "Scorecard"], ["5", "Simple 1-5"], ["10", "Simple 1-10"]];
  let h = '<div class="panel"><h3>Rating style</h3><div class="chips" style="margin:0 0 .5rem" role="group" aria-label="Rating style">' + modes.map(m => '<button class="chip" aria-pressed="' + (p.mode === m[0]) + '" data-a="rmode" data-id="' + m[0] + '">' + m[1] + "</button>").join("") + '</div><p class="meta">Simple styles give a show one overall score. The scorecard rates six categories and builds the final score from what matters to you. Changing style never changes ratings you already gave.</p></div>';
  if (p.mode === "card") h += '<div class="panel"><h3>What matters to you</h3><div class="chips" role="group" aria-label="Presets">' + p.presets.map(x => '<button class="chip" aria-pressed="' + x.active + '" data-a="rpreset" data-id="' + x.key + '">' + esc(x.label) + "</button>").join("") + "</div>" +
    p.criteria.map(c => '<div class="crit"><div><b>' + esc(c.name) + '</b><div class="meta">' + c.share + '% of the final score</div></div><div class="seg" role="group" aria-label="' + esc(c.name) + ' importance">' + p.levels.map((l, i) => '<button aria-pressed="' + (c.weight === i) + '" data-a="rweight" data-id="' + c.key + "|" + i + '">' + l + "</button>").join("") + "</div></div>").join("") +
    '<p class="meta" style="margin-top:.6rem">Changing importance recalculates every final score, so your scores always reflect your current taste. The category scores you gave are never changed.</p></div>';
  else h += '<div class="empty">The scorecard is off. Switch to Scorecard to weigh categories. Ratings you already gave with it keep their category scores.</div>';
  return h + '<div class="panel"><h3>Shows you watched before The Counting</h3><p class="meta">The Counting never asks you to rate your old shows. If you want to, add one you have already watched, say how much of it you saw, and rate it.</p><div style="margin-top:.6rem"><button class="btn sm" data-a="seenpage">Add a show I have already watched</button></div></div>';
}
function rRanks() {
  const r = S.rt.rank, p = S.rt.profile; if (!r) return '<div class="spin">Loading...</div>';
  let h = '<div class="chips" role="group" aria-label="Ranking scope">' + [["overall", "Overall"]].concat(p.criteria.map(c => [c.key, c.name])).map(x => '<button class="chip" aria-pressed="' + (r.scope === x[0]) + '" data-a="rscope" data-id="' + x[0] + '">' + esc(x[1]) + "</button>").join("") + "</div>";
  if (!r.items.length) return h + '<div class="empty">Nothing rated yet. Finish a show and rate it to see rankings here.</div>';
  h += '<div class="panel">' + r.items.map((x, i) => '<div class="rk"><b>' + (i + 1) + '</b><div><button class="back" style="text-decoration:none;color:inherit;padding:0;font-weight:600" data-a="open" data-id="' + x.id + '">' + esc(x.name) + "</button>" + (x.moved ? '<div class="meta">' + (x.moved === "up" ? "Moved up" : "Moved down") + " by your comparisons</div>" : "") + (x.seasons ? '<div class="meta">Includes your season scores</div>' : "") + "</div><span>" + esc(x.score) + "</span></div>").join("") + "</div>";
  return h + (r.skipped ? '<p class="meta">' + r.skipped + " show" + (r.skipped > 1 ? "s" : "") + " rated with a simple score are not in this category ranking.</p>" : "");
}
function rArena() {
  const a = S.rt.arena; if (!a) return '<div class="spin">Loading...</div>';
  const R = S.rt.round, sc = S.rt.arenaScope === "all" ? "overall" : S.rt.arenaScope, q = n => "roughly " + n + " question" + (n === 1 ? "" : "s");
  const cats = a.by_scope.filter(c => c.scope !== "overall").sort((x, y) => y.weight - x.weight);
  let h = '<div class="panel"><div class="switch"><span>Only settle my top three<br><span class="meta">Fewer questions: it stops once the best three in a view are in order.</span></span><button class="tog" role="switch" aria-checked="' + a.top_only + '" aria-label="Only settle my top three" data-a="rtop"></button></div>' +
    '<div class="switch"><span>Only compare shows that share a genre</span><button class="tog" role="switch" aria-checked="' + a.same_genre + '" aria-label="Same genre only" data-a="rgenre"></button></div>' +
    '<p class="meta" style="margin-top:.4rem">The arena only asks about shows you scored 4 out of 5 or higher that are tied or within half a point, because that is where scores bunch up. It skips pairs your earlier answers already settle. ' + a.settled + " comparison" + (a.settled === 1 ? "" : "s") + " settled so far.</p></div>";
  h += '<div class="chips" role="group" aria-label="Arena view"><button class="chip" aria-pressed="' + (sc === "overall") + '" data-a="rascope" data-id="overall">Overall</button>' +
    cats.map(c => '<button class="chip' + (c.questions ? "" : " dim") + '" aria-pressed="' + (sc === c.scope) + '" data-a="rascope" data-id="' + c.scope + '">' + esc(c.name) + "</button>").join("") + "</div>";
  if (!R.active && !R.done) {
    if (!a.next) return h + '<div class="empty">No close calls to settle in this view right now. Pick another category, rate more shows, or turn off the genre filter.</div>';
    return h + '<div class="panel"><h2>Ready when you are</h2><p class="sub">A round is five quick picks, and you can stop any time. There is ' + q(a.questions) + ' in all for this view, and you never have to finish. Categories you marked Essential or Important are listed first, one tap away.</p><div style="margin-top:.9rem"><button class="btn pri" data-a="rstart">Start a round of 5</button></div></div>';
  }
  if (R.done || !a.next) {
    return h + '<div class="panel"><h2>' + (a.next ? "Round complete" : "All settled here") + '</h2><p class="sub">' + R.n + " pick" + (R.n === 1 ? "" : "s") + " this round. " + (a.next ? "There is more waiting in this view, whenever you feel like it." : "Nothing else is close in this view.") + '</p><div class="row" style="margin-top:.9rem">' + (a.next ? '<button class="btn pri" data-a="rstart">Another round</button>' : "") + '<button class="btn" data-a="rstop">Done for now</button><button class="btn" data-a="rtab" data-id="ranks">See rankings</button></div></div>';
  }
  const m = a.next, key = m.scope + "|" + m.a.id + "|" + m.b.id + "|", vc = x => '<div class="vsc"><div style="display:flex;justify-content:center">' + poster({ id: x.id, name: x.name, poster_path: x.poster_path }) + '</div><b style="display:block;margin-top:.5rem">' + esc(x.name) + '</b><span class="meta">' + esc(x.score) + "</span></div>";
  return h + '<div class="panel"><div class="row" style="justify-content:space-between"><span class="meta">Pick ' + (R.n + 1) + " of " + R.total + '</span><button class="btn quiet" data-a="rstop">End round</button></div><h2 style="margin:.3rem 0">' + esc(m.scope_name) + ': which is better?</h2><p class="meta">' + (m.exact ? "You gave these the same score." : "Your scores are within half a point of each other.") + '</p><div class="vs">' + vc(m.a) + vc(m.b) + '</div><div style="display:grid;gap:.5rem">' +
    btn("rcmp", key + "a", esc(m.a.name) + " is better", "pri") + btn("rcmp", key + "b", esc(m.b.name) + " is better", "pri") + btn("rcmp", key + "same", "About the same") + btn("rcmp", key + "skip", "Cannot compare", "quiet") + "</div></div>";
}
function rFavs() {
  const f = S.rt.favs; if (!f) return '<div class="spin">Loading...</div>';
  if (!f.length) return '<div class="empty">No favourite episodes yet. Tap the heart on any watched episode.</div>';
  return '<div class="panel">' + f.map(x => '<div class="rk" style="grid-template-columns:1fr auto"><div><b>' + esc(x.show) + '</b><div class="meta">' + esc(x.label) + (x.name ? " " + esc(x.name) : "") + '</div></div><button class="btn quiet" data-a="fav" data-id="' + x.episode_id + '" data-from="favs">Remove</button></div>').join("") + "</div>";
}
const mRatePrompt = (id, name) => "<h2>You finished " + esc(name) + ". Rate it?</h2><p class=\"sub\">It takes about ten seconds. You can also do it later from the show page.</p><div class=\"stack\">" + btn("rateshow", id, "Rate now", "pri") + btn("close", "", "Later") + "</div>";
function rateBody() {
  const d = S.draft; if (!d) return; let h = "";
  if (d.mode === "card") {
    h += d.p.criteria.map(c => { const ig = c.weight === 0; return '<div class="slider" style="' + (ig ? "opacity:.55" : "") + '"><span>' + esc(c.name) + (ig ? ' <small class="meta">(ignored)</small>' : "") + '</span><input type="range" min="1" max="5" step="1" value="' + d.s[c.key] + '" data-r="' + c.key + '" aria-label="' + esc(c.name) + ' score"><b id="sv-' + c.key + '">' + d.s[c.key] + "</b></div>"; }).join("");
    h += '<div class="switch" style="margin-top:.5rem"><span>Add a gut score (kept separate)</span><button class="tog" role="switch" aria-checked="' + d.gutOn + '" aria-label="Add a gut score" data-a="gut"></button></div>';
    if (d.gutOn) h += '<div class="slider"><span>Gut feeling</span><input type="range" min="1" max="5" step="1" value="' + d.g + '" data-r="g" aria-label="Gut score"><b id="gv">' + d.g + "</b></div>";
  } else { const m = d.mode === "10" ? 10 : 5; h += '<div class="slider"><span>Overall</span><input type="range" min="1" max="' + m + '" step="1" value="' + d.o + '" data-r="o" aria-label="Overall score"><b id="ov">' + d.o + "</b></div>"; }
  $("#ratebody").innerHTML = h; rateFinal();
}
function rateFinal() { const d = S.draft; if (!d) return; $("#final").textContent = scoreText(draftFinal(d), d.p.max) + (d.mode === "card" ? " weighted" : "") + (d.mode === "card" && d.gutOn ? "   Gut " + d.g + " / 5" : ""); }
function openRateModal(det) {
  const p = det.rating_profile, cur = det.rating_info.current;
  const d = { id: det.id, mode: p.mode, p, s: {}, o: p.mode === "10" ? 7 : 4, g: 4, gutOn: false };
  p.criteria.forEach(c => { d.s[c.key] = cur && cur.scores ? cur.scores[c.key] : 3; });
  if (cur) { d.o = Math.max(1, Math.round(cur.fraction * (p.mode === "10" ? 10 : 5))); if (cur.gut != null) { d.g = cur.gut; d.gutOn = true; } }
  S.draft = d;
  S.modal = "<h2>" + (cur ? "Edit your rating of " : "Rate ") + esc(det.name) + '</h2><p class="meta">' + (p.mode === "card" ? "Score each category from 1 to 5. The importance you set in Ratings turns these into one final score." : "One overall score. You can switch to the scorecard in Ratings.") + '</p><div id="ratebody" style="margin-top:.6rem"></div><div class="final" id="final"></div><div class="stack">' + btn("saverate", det.id, "Save rating", "pri") + btn("close", "", "Cancel", "quiet") + "</div>";
  render(); rateBody();
}
function mSeenThrough(det) {
  const seasons = det.season_list.map(x => x.number);
  return "<h2>How much of " + esc(det.name) + " have you seen?</h2><p class=\"sub\">Episodes are marked without dates, so they count toward progress but not your monthly stats. " + esc(det.name) + " is on your watch list until you choose.</p><div class=\"stack\">" + btn("seenthru", det.id + "|all", "All of it", "pri") + seasons.map(n => btn("seenthru", det.id + "|" + n, "Up to the end of season " + n)).join("") + btn("close", "", "Not now", "quiet") + "</div>";
}

/* ---------- shell ---------- */
function render() {
  const views = { setup: vSetup, library: vLibrary, towatch: vToWatch, discover: vDiscover, search: vSearch, show: vShow, stats: vStats, log: vLog, ratings: vRatings, data: vData, settings: vSettings };
  $("#main").innerHTML = views[S.view]();
  const counts = S.app ? S.app.counts : {};
  const flipTo = effectiveTheme() === "dark" ? "light" : "dark";
  const themeBtn = '<button class="themebtn" data-a="themeflip" aria-label="Switch to ' + flipTo + ' mode" title="Switch to ' + flipTo + ' mode">' + themeIcon + "</button>";
  const tabs = S.view === "setup" ? [] : [["library", "Library", counts.watching], ["towatch", "To watch", counts.plan], ["discover", "Discover"], ["ratings", "Ratings"], ["search", "Add show"]];
  const inProf = ["stats", "log", "data", "settings"].includes(S.view);
  $("#tabs").innerHTML = tabs.map(t => '<button class="tab" data-a="nav" data-id="' + t[0] + '"' + (S.view === t[0] || (S.view === "show" && t[0] === "library") ? ' aria-current="page"' : "") + ">" + (t[0] === "search" ? '<span class="lg">Add show</span><span class="sm">Add</span>' : t[1]) + (t[2] != null ? '<span class="n">' + t[2] + "</span>" : "") + "</button>").join("") +
    (S.view === "setup" ? "" : '<div class="profwrap"><button class="tab prof" data-a="menu" aria-haspopup="menu" aria-expanded="' + S.menu + '"' + (inProf ? ' aria-current="page"' : "") + '><span class="avatar" aria-hidden="true">Me</span><span class="plabel">Profile</span></button>' + (S.menu ? '<div class="menu" role="menu"><div class="mh">Your space</div><button role="menuitem" data-a="nav" data-id="stats">Stats</button><button role="menuitem" data-a="nav" data-id="log">Watch log</button><button role="menuitem" data-a="nav" data-id="settings">Settings</button><button role="menuitem" data-a="tourstart">Take the tour</button>' + (S.app && S.app.remote ? "" : '<button role="menuitem" data-a="nav" data-id="data">Backups and data</button>') + '</div>' : "") + "</div>");
  $("#themeslot").innerHTML = themeBtn;
  $("#layer").innerHTML = S.modal ? '<div class="scrim" data-a="close"><div class="modal' + (S.tour ? " tourmodal" : "") + '" role="dialog" aria-modal="true" aria-label="' + (S.tour ? "Tour" : S.offer ? "Welcome" : "Dialog") + '">' + S.modal + "</div></div>" : "";
  if (S.view === "search") renderResults();
}

/* ---------- actions ---------- */
async function doMark(id, resolve) {
  await run(async () => {
    const r = await api("/api/mark", "POST", { episode_id: +id, resolve: resolve });
    if (r.prompt === "rewatch") { S.modal = mRewatch(id); return; }
    if (r.prompt === "gaps") { S.modal = mGaps(id, r.count); return; }
    S.modal = null;
    toast(r.message || (r.started ? "Started " + (r.show ? r.show.name : "the show") + " and moved it to Watching." : "Marked watched."));
    await refreshState(); await load(S.view);
  });
  render();
}
async function act(a, id, el) {
  const d = el ? el.dataset : {};
  switch (a) {
    case "nav": if (id === "search") S.search.seen = false; return go(id);
    case "menu": S.menu = !S.menu; return render();
    case "close":
      if ((S.tour || S.offer) && S.guide && S.guide.state.tour === "") await guideSave({ tour: "skipped" });
      S.modal = null; S.sdraft = null; S.pair = null; S.tour = null; S.offer = false; return render();
    case "tourstart": S.menu = false; S.offer = false; S.tour = { i: 0 }; S.modal = tourModal(); return render();
    case "tournext": case "tourback": S.tour.i = Math.max(0, Math.min(tourSteps().length - 1, S.tour.i + (a === "tournext" ? 1 : -1))); S.modal = tourModal(); return render();
    case "tourskip": if (S.guide && S.guide.state.tour === "") await guideSave({ tour: "skipped" }); S.tour = null; S.offer = false; S.modal = null; return render();
    case "tourdone": await guideSave({ tour: "done" }); S.tour = null; S.modal = null; toast("That is the tour. The Getting started list in your Library can walk you through it for real."); return render();
    case "tourreplay": S.tour = { i: 0 }; S.modal = tourModal(); return render();
    case "selftest": {
      S.self = { busy: true };
      render();
      try { const r = await api("/api/selftest", "POST", {}); S.self = { text: r.text, ok: r.ok }; }
      catch (e) { S.self = { err: e.message }; }
      return render();
    }
    case "selfcopy": { const t = $(".selfout"); if (t) { t.select(); try { await navigator.clipboard.writeText(t.value); toast("Copied."); } catch (e) { document.execCommand("copy"); toast("Copied."); } } return; }
    case "tipok": await guideSave({ tip: id }); return render();
    case "chkhide": await guideSave({ checklist: "dismissed" }); return render();
    case "chkgo": return guideShowMe(id);
    case "guidereset": await guideSave({ reset: true }); toast("Tips, the checklist and the tour offer are back."); return render();
    case "back": return go(S.prevView || "library");
    case "open": S.showId = +id; S.prevView = S.view === "show" ? S.prevView : S.view; return go("show");
    case "lib": S.lib = id; return reload();
    case "sortready": S.sortReady = true; return render();
    case "sortshort": S.sortReady = false; return render();
    case "readyonly": S.readyOnly = !S.readyOnly; return render();
    case "keep": S.keep[id] = true; return render();
    case "complete": { let name = ""; await run(async () => { const r = await api("/api/shows/" + id + "/status", "POST", { status: "completed" }); name = r.name; if (!r.rating) S.modal = mRatePrompt(id, r.name); }); toast("Marked completed."); return reload(); }
    case "mark": return doMark(id);
    case "resolve": return doMark(id, d.r);
    case "upto": await run(async () => {
      const r = await api("/api/seen-up-to", "POST", { episode_id: +id });
      toast("Marked " + r.marked + " episode" + (r.marked === 1 ? "" : "s") + (r.skipped ? ". " + r.skipped + " already watched, left alone." : ".") + (r.started ? " Moved to Watching." : ""));
      await refreshState(); await load("show");
    }); return render();
    case "syn": S.revealed[id] = !S.revealed[id]; return render();
    case "tseason": { const sh = S.show; const cur = id in S.open ? S.open[id] : null; if (cur === null) { const num = id.split(":")[1]; const def = num === "sp" ? false : (sh.next ? String(sh.next_season) === num : String(sh.season_list[0].number) === num); S.open[id] = !def; } else S.open[id] = !cur; return render(); }
    case "ttl": case "abs": case "incsp": {
      const key = { ttl: "hide_titles", abs: "absolute_numbering", incsp: "include_specials" }[a];
      await run(async () => { S.show = await api("/api/shows/" + S.show.id + "/overrides", "POST", { [key]: !S.show.overrides[key] }); });
      return render();
    }
    case "fold": S.fold[id] = !S.fold[id]; return render();
    case "sqgo": {
      const [n, epId] = id.split("|"); S.open[S.show.id + ":" + n] = true; render();
      const el = document.getElementById("ep-" + epId); if (el) { if (el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); }
      return;
    }
    case "castcount": S.castCounts = !S.castCounts; return render();
    case "refresh": await run(async () => { S.show = await api("/api/shows/" + S.show.id + "/refresh", "POST", {}); toast("Show data refreshed."); }); return render();
    case "remove": S.modal = mConfirm("Remove " + S.show.name + "?", "It disappears from your lists. Your watch history is kept, so adding it again brings your progress back.", "removeyes", "", "Remove from library"); return render();
    case "removeyes": await run(() => api("/api/shows/" + S.show.id, "DELETE", {})); S.modal = null; toast("Removed from your library."); return go("library");
    case "addshow": await run(async () => {
      const s = await api("/api/shows", "POST", { tmdb_id: +id, status: d.st });
      const hit = S.search.results.find(r => r.id === +id); if (hit) hit.in_library = s.status;
      toast("Added " + s.name + (d.st === "plan" ? " to your watch list." : " to your library."));
      await refreshState();
    }); if (d.st === "watching") { S.showId = +id; S.prevView = "library"; return go("show"); } return render();
    case "savekey": {
      const v = $("#key").value;
      try { await api("/api/settings/key", "POST", { key: v }); S.settingsErr = null; toast("Key saved."); await refreshState(); }
      catch (e) { S.settingsErr = e.message; return render(); }
      if (S.view === "setup") { await guideLoad(); await go("library"); return maybeOfferTour(); }
      return go("settings");
    }
    case "opendata": return run(() => api("/api/open-data-folder", "POST", {}));
    case "themeflip": return setTheme(effectiveTheme() === "dark" ? "light" : "dark");
    case "settheme": return setTheme(id);
    case "lanon": await run(async () => { S.lan = await api("/api/lan/enable", "POST", { on: !S.lan.enabled }); toast(S.lan.running ? "Phone access is on." : "Phone access is off."); }); return render();
    case "lanpair": await run(async () => { S.pair = await api("/api/lan/pair", "POST", {}); S.modal = pairModal(); }); return render();
    case "lanforget": await run(async () => { S.lan = await api("/api/lan/forget", "POST", { id: +id }); toast("That device was forgotten."); }); return render();
    case "securedns": await run(async () => { S.app = await api("/api/settings/network", "POST", { secure_dns: !S.app.secure_dns }); }); return render();
    case "diagnose": {
      const box = $("#diag"); box.innerHTML = '<p class="meta" style="margin-top:.6rem">Checking...</p>';
      try {
        const r = await api("/api/diagnose", "POST", {});
        box.innerHTML = '<div style="margin-top:.6rem">' + r.steps.map(s => '<div class="backup-row"><span><b>' + (s.ok ? "Passed" : "Failed") + ":</b> " + esc(s.name) + '</span><span class="meta">' + esc(s.detail) + "</span></div>").join("") + "</div>";
      } catch (e) { box.innerHTML = '<div class="err" style="margin-top:.6rem">' + esc(e.message) + "</div>"; }
      return;
    }
    case "tmdb-api": if (S.app && S.app.remote) { window.open("https://www.themoviedb.org", "_blank", "noopener"); return; } return run(() => api("/api/open-url", "POST", { url: "https://www.themoviedb.org/settings/api" }));
    case "browse": {
      let folder = null;
      if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) folder = await window.pywebview.api.pick_folder();
      else folder = (await run(() => api("/api/pick-folder", "POST", {}))) && null;
      if (folder) $("#bfolder").value = folder; else toast("Type or paste a folder path instead."); return;
    }
    case "savebackup": await run(async () => { S.app = await api("/api/settings/backup", "POST", { folder: $("#bfolder").value.trim(), keep: $("#bkeep").value }); toast("Backup settings saved."); }); return render();
    case "backupnow": await run(async () => { S.backups = await api("/api/backups/now", "POST", {}); toast("Backup saved."); await refreshState(); }); return render();
    case "openbackups": return run(() => api("/api/backups/open-folder", "POST", {}));
    case "restore": S.modal = mConfirm("Restore this backup?", "Your current lists and history are replaced by the backup. The Counting saves a copy of the current data first, so you can undo this.", "restoreyes", id, "Restore backup"); return render();
    case "restoreyes": await run(async () => { await api("/api/backups/restore", "POST", { name: id }); toast("Backup restored."); }); S.modal = null; return go("library");
    case "export": return run(async () => { const r = await api("/api/export", "POST", {}); toast("Exported to " + r.path); });
    case "importpick": return $("#importfile").click();
    case "rateseasons": await run(() => openSeasonModal(+id)); return;
    case "spick": { const [n, v] = id.split("|").map(Number); const d = S.sdraft; d.scores[n] = d.scores[n] === v ? null : v; S.modal = seasonModal(); return render(); }
    case "smode": S.sdraft.mode = id; S.modal = seasonModal(); return render();
    case "ssave": {
      const d = S.sdraft; let info;
      await run(async () => {
        const scores = Object.fromEntries(Object.entries(d.scores).filter(([, v]) => v != null));
        info = await api("/api/shows/" + d.id + "/seasons/rate", "POST", { scores });
        info = await api("/api/shows/" + d.id + "/seasons/prefs", "POST", { mode: d.mode, mix: d.mix });
      });
      if (!info) return;
      d.info = info;
      if (info.pending.length) { d.step = "tie"; S.modal = seasonModal(); toast("Season scores saved."); return render(); }
      S.modal = null; S.sdraft = null; toast("Season scores saved."); return reload();
    }
    case "stie": {
      const [a, b, res] = id.split("|"), d = S.sdraft;
      await run(async () => { d.info = await api("/api/shows/" + d.id + "/seasons/compare", "POST", { a: +a, b: +b, result: res }); });
      if (!d.info.pending.length) { S.modal = null; S.sdraft = null; toast("Saved."); return reload(); }
      S.modal = seasonModal(); return render();
    }
    case "sdone": S.modal = null; S.sdraft = null; return reload();
    case "rateshow": await run(async () => { openRateModal(await api("/api/shows/" + id)); }); return;
    case "gut": S.draft.gutOn = !S.draft.gutOn; rateBody(); return;
    case "saverate": {
      const d = S.draft; const body = d.mode === "card" ? { show_id: d.id, mode: "card", scores: d.s, gut: d.gutOn ? d.g : null } : { show_id: d.id, mode: d.mode, overall: d.o };
      await run(async () => { const r = await api("/api/ratings", "POST", body); toast("Rating saved. Final score: " + r.current.final + "."); });
      S.modal = null; S.draft = null; return reload();
    }
    case "fav": await run(async () => { const r = await api("/api/favourites/toggle", "POST", { episode_id: +id }); toast(r.favourite ? "Added to favourites." : "Removed from favourites."); await load(S.view); }); return render();
    case "rtab": S.rt.tab = id; return reload();
    case "rscope": S.rt.scope = id; return reload();
    case "rmode": await run(async () => { S.rt.profile = await api("/api/ratings/profile", "POST", { mode: id }); toast("Rating style changed. Existing ratings are kept."); }); return render();
    case "rpreset": await run(async () => { S.rt.profile = await api("/api/ratings/profile", "POST", { preset: id }); }); return render();
    case "rweight": { const [k, i] = id.split("|"); await run(async () => { S.rt.profile = await api("/api/ratings/profile", "POST", { weights: { [k]: +i } }); }); return render(); }
    case "rgenre": await run(async () => { await api("/api/ratings/profile", "POST", { same_genre: !S.rt.arena.same_genre }); S.rt.arena = await api("/api/ratings/arena?scope=" + S.rt.arenaScope); }); return render();
    case "rtop": await run(async () => { await api("/api/ratings/profile", "POST", { top_only: !S.rt.arena.top_only }); S.rt.arena = await api("/api/ratings/arena?scope=" + S.rt.arenaScope); }); return render();
    case "rascope": S.rt.arenaScope = id; S.rt.round = { n: 0, total: 5, active: false, done: false }; return reload();
    case "rstart": S.rt.round = { n: 0, total: 5, active: true, done: false }; return render();
    case "rstop": S.rt.round = { n: 0, total: 5, active: false, done: false }; return reload();
    case "rcmp": {
      const [sc, a, b, res] = id.split("|");
      await run(async () => {
        S.rt.arena = await api("/api/ratings/compare", "POST", { scope: sc, a: +a, b: +b, result: res, view: S.rt.arenaScope });
        const R = S.rt.round; R.n++; if (R.n >= R.total || !S.rt.arena.next) R.done = true;
        toast(res === "skip" ? "Skipped. That pair will not come up again." : "Comparison saved.");
      }); return render();
    }
    case "seenpage": S.search = { q: "", results: null, err: null, seen: true }; return go("search");
    case "dmode": S.discMode = id; return reload();
    case "dadd": await run(async () => { const s = await api("/api/shows", "POST", { tmdb_id: +id, status: "plan", source: "from recommendation" }); toast("Added " + s.name + " to your watch list."); await refreshState(); await load("discover"); }); return render();
    case "ddismiss": await run(async () => { await api("/api/discover/dismiss", "POST", { show_id: +id }); toast("Got it. That show will not be suggested again."); await load("discover"); }); return render();
    case "dseen": case "addseen": {
      await run(async () => {
        await api("/api/shows", "POST", { tmdb_id: +id, status: "plan", source: a === "dseen" ? "from recommendation" : "manual" });
        const det = await api("/api/shows/" + id); S.modal = mSeenThrough(det); await refreshState();
      }); return render();
    }
    case "seenthru": {
      const [sid, through] = id.split("|");
      await run(async () => {
        const r = await api("/api/shows/seen", "POST", { tmdb_id: +sid, through: through === "all" ? "all" : +through });
        S.modal = null; toast("Added " + r.name + " with " + r.progress.watched + " episodes marked.");
        await refreshState();
        if (r.ask_rating) { S.modal = mRatePrompt(sid, r.name); }
        if (S.view === "discover") await load("discover"); else if (S.view === "search" && S.search.results) { const hit = S.search.results.find(x => x.id === +sid); if (hit) hit.in_library = r.status; }
      }); return render();
    }
    case "importyes": await run(async () => { const r = await api("/api/import", "POST", S.pendingImport); toast("Imported " + r.shows + " shows and " + r.events + " watch events. Fetching show data..."); }); S.pendingImport = null; S.modal = null; return go("library");
  }
}

document.addEventListener("click", e => {
  if (S.menu && !e.target.closest(".profwrap")) { S.menu = false; if (!e.target.closest("[data-a]")) render(); }
  const b = e.target.closest("[data-a]"); if (!b) return;
  if (b.classList.contains("scrim") && e.target !== b) return;
  act(b.dataset.a, b.dataset.id, b);
});
document.addEventListener("change", async e => {
  if (e.target.id === "stsel") {
    await run(async () => { await api("/api/shows/" + S.show.id + "/status", "POST", { status: e.target.value }); S.show = await api("/api/shows/" + S.show.id); await refreshState(); toast("Status updated."); if (e.target.value === "completed" && !S.show.rating_info.current) S.modal = mRatePrompt(S.show.id, S.show.name); });
    render();
  }
  if (e.target.id === "importfile" && e.target.files[0]) {
    try { S.pendingImport = JSON.parse(await e.target.files[0].text()); }
    catch (err) { toast("That file could not be read."); return; }
    e.target.value = "";
    S.modal = mConfirm("Replace your data with this file?", "Your lists and watch history become what is in the file. The Counting saves a backup of the current data first.", "importyes", "", "Import"); render();
  }
});
document.addEventListener("input", e => {
  if (e.target.dataset.s === "mix" && S.sdraft) { S.sdraft.mix = +e.target.value; $("#mixv").textContent = S.sdraft.mix + "%"; $("#spreview").textContent = previewSeasons(S.sdraft); return; }
  const k = e.target.dataset.r; if (!k || !S.draft) return; const v = parseFloat(e.target.value), d = S.draft;
  if (k === "o") { d.o = v; $("#ov").textContent = v; } else if (k === "g") { d.g = v; $("#gv").textContent = v; } else { d.s[k] = v; $("#sv-" + k).textContent = v; }
  rateFinal();
});
let searchTimer;
document.addEventListener("input", e => {
  if (e.target.id !== "q") return;
  const q = e.target.value; S.search.q = q; clearTimeout(searchTimer);
  if (q.trim().length < 2) { S.search.results = null; S.search.err = null; renderResults(); return; }
  searchTimer = setTimeout(async () => {
    try { const r = await api("/api/search?q=" + encodeURIComponent(q.trim())); if (S.search.q === q) { S.search.results = r.results; S.search.err = null; } }
    catch (err) { if (err.kind === "nokey") { S.view = "setup"; render(); return; } S.search.err = err.message; }
    renderResults();
  }, 350);
});
document.addEventListener("keydown", e => {
  if (S.tour && (e.key === "ArrowRight" || e.key === "ArrowLeft")) { e.preventDefault(); act(e.key === "ArrowRight" ? "tournext" : "tourback", ""); return; }
  if (e.key === "Escape" && (S.modal || S.menu)) { if (S.modal) act("close", ""); else { S.menu = false; render(); } }
});
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "key") act("savekey"); });
$("#tmdblink").addEventListener("click", () => act("tmdb-api"));

/* ---------- start ---------- */
window.addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/bye?t=" + encodeURIComponent(TOKEN)); } catch (e) { /* closing anyway */ } });
async function boot() {
  api("/api/ping", "POST", {}).catch(() => {});
  try { await refreshState(); } catch (e) { $("#main").innerHTML = '<div class="err">The Counting could not reach its own engine. Close and reopen the app.</div>'; return; }
  if (S.app.remote) { try { const t = localStorage.getItem("tc-theme"); if (t) S.app.theme = t; } catch (e) { /* ignore */ } }
  applyTheme(S.app.theme);
  await guideLoad();
  if (!S.app.has_key) { S.view = "setup"; render(); }
  else { await go("library"); maybeOfferTour(); }
  setInterval(async () => {
    try {
      await api("/api/ping", "POST", {});
      if (S.app && S.app.pending_sync) { const before = S.app.pending_sync; await refreshState(); if (S.app.pending_sync !== before && (S.view === "library" || S.view === "towatch")) { await load(S.view); render(); } }
    } catch (e) { /* the engine may be closing */ }
  }, 4000);
}
boot();
