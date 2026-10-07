// Browser-level test: loads the real UI in jsdom and clicks through it. Usage: node e2e.js <url>
const { JSDOM } = require(process.env.JSDOM_PATH || "jsdom");
const url = process.argv[2];
let failed = 0;
const ok = (name, cond) => { console.log((cond ? "ok   " : "FAIL ") + name); if (!cond) failed++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const dom = await JSDOM.fromURL(url, {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, w.location.href), o); w.scrollTo = () => {}; },
  });
  const w = dom.window, d = w.document;
  const text = () => d.body.textContent.replace(/\s+/g, " ");
  const waitFor = async (fn, label) => { for (let i = 0; i < 160; i++) { try { if (fn()) return true; } catch (e) {} await sleep(50); } console.log("   (timeout waiting for: " + label + ")"); return false; };
  const click = sel => { const el = d.querySelector(sel); if (!el) throw new Error("missing " + sel); el.click(); };
  const clickText = (sel, t) => { const el = [...d.querySelectorAll(sel)].find(e => e.textContent.includes(t)); if (!el) throw new Error("missing " + sel + " with " + t); el.click(); };
  const setVal = (sel, v, ev) => { const el = d.querySelector(sel); el.value = v; el.dispatchEvent(new w.Event(ev || "input", { bubbles: true })); };

  // first run: setup screen, rejects a bad key, accepts a good one
  ok("setup screen shown on first run", await waitFor(() => text().includes("Welcome to The Counting"), "setup"));
  setVal("#key", "wrongkey"); click('[data-a="savekey"]');
  ok("bad key gives a clear message", await waitFor(() => text().includes("rejected the API key"), "bad key"));
  setVal("#key", "goodkey123"); click('[data-a="savekey"]');
  ok("good key opens the library", await waitFor(() => d.querySelector("h1") && d.querySelector("h1").textContent === "Library", "library"));
  ok("empty library invites adding a show", text().includes("Add your first show"));

  // the welcome offer, the tour, the checklist and the tips
  ok("a welcome offer appears once the key is saved", await waitFor(() => text().includes("two-minute tour") && d.querySelector('[data-a="tourstart"]') !== null, "offer"));
  click('[data-a="tourstart"]');
  ok("the tour opens on step 1 of 8", await waitFor(() => text().includes("Step 1 of 8") && text().includes("A private place to keep track"), "tour step 1"));
  const titles = ["Welcome to The Counting", "One square for every episode", "Add the shows you watch", "No spoilers", "Rate shows your way", "Rankings and the arena", "Discover and stats", "Your data, and your phone"];
  for (let i = 1; i < 8; i++) {
    click('[data-a="tournext"]');
    ok("tour step " + (i + 1) + " is " + titles[i], await waitFor(() => text().includes("Step " + (i + 1) + " of 8") && d.querySelector(".tour > h2").textContent === titles[i], "step " + (i + 1)));
    if (i === 1) ok("step 2 draws a real library card with squares", d.querySelector(".tour .demo .lcard") !== null && d.querySelectorAll(".tour .demo .lcard .sq i.on").length === 5 && d.querySelectorAll(".tour .demo .lcard .sq i.next").length === 1);
    if (i === 3) ok("step 4 shows a hidden episode next to one with a Reveal button", d.querySelector(".tour .demo .still.lock") !== null && text().includes("Reveal synopsis"));
  }
  ok("the pictures cannot be clicked: inert, and no actions inside them", [...d.querySelectorAll(".tour .demo")].every(x => x.hasAttribute("inert") && !x.querySelector("[data-a]")));
  ok("the last step offers Finish", d.querySelector('[data-a="tourdone"]') !== null && d.querySelector('[data-a="tournext"]') === null);
  click('[data-a="tourback"]');
  ok("Back goes back one step", await waitFor(() => text().includes("Step 7 of 8"), "back"));
  click('[data-a="tournext"]'); click('[data-a="tourdone"]');
  ok("finishing closes the tour and remembers it", await waitFor(() => d.querySelector(".tour") === null && w.eval("S.guide.state.tour") === "done", "tour done"));
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="tourstart"]', "Take the tour");
  ok("the tour can be taken again from the Profile menu", await waitFor(() => text().includes("Step 1 of 8"), "replay"));
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  ok("the arrow keys move through the tour", await waitFor(() => text().includes("Step 2 of 8"), "arrow"));
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  ok("Escape closes it without changing what was saved", await waitFor(() => d.querySelector(".tour") === null, "escape") && w.eval("S.guide.state.tour") === "done");

  ok("the Library carries a Getting started list with nothing done", text().includes("Getting started") && text().includes("0 of 7 done"));
  clickText('[data-a="chkgo"]', "");
  ok("Show me takes you to the search box and highlights it", await waitFor(() => d.querySelector("#q") !== null && d.querySelector("#q").classList.contains("pulse"), "pulse"));
  clickText(".tab", "Library");
  await waitFor(() => d.querySelector("h1") && d.querySelector("h1").textContent === "Library", "back to library");

  // search and add
  click('.tab[data-id="search"]');
  ok("search page", await waitFor(() => d.querySelector("#q"), "search box"));
  setVal("#q", "harbour");
  ok("search results appear", await waitFor(() => text().includes("Harbour Lights") && text().includes("Add to watch list"), "results"));
  clickText('[data-a="addshow"]', "I am watching this");
  ok("watching opens the show page", await waitFor(() => d.querySelector("h1") && d.querySelector("h1").textContent === "Harbour Lights", "show page"));
  ok("no episode synopsis leaked for locked episodes", !text().includes("Synopsis of 1-2") && !text().includes("Synopsis of 1-3"));
  ok("locked episodes explain themselves", text().includes("stay hidden until you finish the previous episode"));

  // mark episode 1 (single), then jump to episode 3 -> gap prompt
  let checks = () => [...d.querySelectorAll('.ep [data-a="mark"]')];
  checks()[0].click();
  ok("first mark works", await waitFor(() => text().includes("1 / 4"), "1/4"));
  ok("unlocked episodes have a Reveal button and no synopsis text in the page", await waitFor(() => d.querySelectorAll('[data-a="syn"]').length >= 2 && !text().includes("Synopsis of 1-1") && !text().includes("Synopsis of 1-2"), "reveal buttons"));
  d.querySelector('[data-a="syn"]').click();
  ok("clicking Reveal expands the synopsis in a box", await waitFor(() => text().includes("Synopsis of 1-1") && d.querySelector(".synbox") !== null && d.querySelector('[data-a="syn"]').getAttribute("aria-expanded") === "true", "reveal"));
  ok("other episodes stay closed", !text().includes("Synopsis of 1-2"));
  d.querySelector('[data-a="syn"]').click();
  ok("and Hide puts it away again", await waitFor(() => !text().includes("Synopsis of 1-1") && d.querySelector(".synbox") === null, "hidden again"));
  ok("episode 3 still locked", !text().includes("Synopsis of 1-3"));
  checks()[3].click();
  ok("gap prompt appears", await waitFor(() => text().includes("Mark the earlier episodes too?"), "gap modal"));
  clickText("[data-r]", "Mark all 2 before it too");
  ok("gap fill marks 4 episodes", await waitFor(() => text().includes("4 / 4") || text().includes("4 of 8"), "4 watched"));

  // rewatch prompt
  ok("season with the next episode opens by default", text().includes("S2E1"));
  clickText('[data-a="tseason"]', "Season 1");
  await waitFor(() => text().includes("Harbour Lights S1E1"), "season 1 open");
  checks()[0].click();
  ok("rewatch prompt appears", await waitFor(() => text().includes("You have already watched this episode"), "rewatch modal"));
  clickText("[data-r]", "rewatching");
  ok("rewatch logged", await waitFor(() => text().includes("Watched x2"), "x2"));

  // the show page: episodes lead, with rating and display rules beside them
  ok("episodes lead and the rating sits in a side column", d.querySelector(".showcols .epcol") !== null && d.querySelector(".showcols .sidecol") !== null && d.querySelector(".sidecol").textContent.includes("Your rating"));
  ok("the artwork hero and a square per episode are there", d.querySelector(".showhero") !== null && d.querySelectorAll(".seasq .sqi").length === 8 && d.querySelectorAll(".seasq .sqi.on").length >= 4);
  ok("display rules and cast are tucked away until wanted", d.querySelector('[data-a="ttl"]') === null && d.querySelector('[data-a="fold"][data-id="rules"]').getAttribute("aria-expanded") === "false");
  click('[data-a="fold"][data-id="rules"]');
  ok("opening display rules shows the switches", await waitFor(() => d.querySelector('[data-a="ttl"]') !== null, "rules open"));
  // display rules
  clickText('[data-a="ttl"]', "");
  ok("hide titles override works", await waitFor(() => text().includes("Title hidden") && !text().includes("Harbour Lights S1E1"), "titles hidden"));
  click('[data-a="ttl"]');
  ok("titles come back", await waitFor(() => text().includes("Harbour Lights S1E1"), "titles back"));
  click('[data-a="abs"]');
  ok("absolute numbering", await waitFor(() => text().includes("S1E1 (#1)"), "abs"));

  const sq = d.querySelector('.seasq .sqi[data-id^="2|"]'); sq.click();
  ok("clicking a square opens that season at that episode", await waitFor(() => d.querySelector('[data-a="tseason"][aria-expanded="true"]') !== null && text().includes("S2E1"), "square jump"));
  // season 2 and up-to-here
  ok("season 2 is open", await waitFor(() => text().includes("S2E4 (#8)"), "s2"));
  const upto = [...d.querySelectorAll('[data-a="upto"]')].pop();
  upto.click();
  ok("seen up to here reports fill", await waitFor(() => text().includes("Marked 4 episodes"), "toast"));
  ok("show reaches 8 of 8", await waitFor(() => text().includes("8 of 8 aired episodes watched"), "8/8"));

  // library banner suggests completing
  clickText(".tab", "Library");
  ok("library shows completion suggestion", await waitFor(() => text().includes("Mark it completed?"), "banner"));
  clickText('[data-a="complete"]', "Mark completed");
  ok("banner clears after completing", await waitFor(() => !text().includes("Mark it completed?") && text().includes("Completed (1)"), "completed"));
  ok("completing offers to rate the show", await waitFor(() => text().includes("You finished Harbour Lights. Rate it?"), "rate prompt"));
  clickText('[data-a="rateshow"]', "Rate now");
  ok("scorecard has six category sliders", await waitFor(() => d.querySelectorAll('#ratebody input[type="range"]').length === 6, "sliders"));
  setVal('[data-r="cine"]', "5"); setVal('[data-r="writing"]', "5");
  ok("live weighted score updates", await waitFor(() => /\d(\.\d)? \/ 5 weighted/.test(d.querySelector("#final").textContent), "final"));
  click('[data-a="gut"]');
  ok("gut score is optional", await waitFor(() => d.querySelector('[data-r="g"]') !== null, "gut slider"));
  clickText('[data-a="saverate"]', "Save rating");
  ok("rating saved", await waitFor(() => text().includes("Rating saved. Final score"), "saved toast"));
  click('[data-a="lib"][data-id="completed"]');
  ok("library card shows your rating", await waitFor(() => text().includes("Your rating:"), "rating on card"));
  d.querySelector('[data-a="open"]').click();
  ok("show page has the rating panel with category chips", await waitFor(() => text().includes("Your rating") && text().includes("Cinematography 5/5") && text().includes("Gut 4/5"), "panel"));
  clickText('[data-a="rateshow"]', "Edit rating");
  await waitFor(() => d.querySelector('[data-r="cine"]'), "edit sliders");
  setVal('[data-r="cine"]', "2");
  clickText('[data-a="saverate"]', "Save rating");
  ok("re-rating keeps the earlier one in history", await waitFor(() => text().includes("Earlier ratings (1)"), "history"));
  if (!text().includes("Harbour Lights S1E1")) clickText('[data-a="tseason"]', "Season 1");
  await waitFor(() => text().includes("Harbour Lights S1E1"), "s1 open");
  clickText('[data-a="fav"]', "Favourite");
  ok("favouriting an episode", await waitFor(() => text().includes("Favourited") && text().includes("Favourite episodes"), "favourited"));

  // season ratings
  ok("a multi-season show offers Rate seasons", await waitFor(() => d.querySelector('[data-a="rateseasons"]') !== null && text().includes("Rate each season to see which was best"), "seasons section"));
  click('[data-a="rateseasons"]');
  ok("the season window has a row of scores per season", await waitFor(() => d.querySelectorAll(".srow").length === 2 && d.querySelectorAll('.np[aria-label="Season 1 score"] button').length === 5, "season rows"));
  ok("it explains that skipping is fine and that nothing changes unless you choose", text().includes("Seasons you skip are left out") && text().includes("Should these scores change the show"));
  click('[data-a="spick"][data-id="1|5"]'); click('[data-a="spick"][data-id="2|3"]');
  ok("the preview says the show's score stays put when counting is off", await waitFor(() => d.querySelector("#spreview").textContent.includes("Seasons average 4 / 5") && d.querySelector("#spreview").textContent.includes("stays"), "preview off"));
  click('[data-a="smode"][data-id="blend"]');
  ok("blend shows a mix slider and a live preview", await waitFor(() => d.querySelector('[data-s="mix"]') !== null && d.querySelector("#spreview").textContent.includes("Counts as"), "blend preview"));
  setVal('[data-s="mix"]', "70");
  ok("moving the slider updates the preview without redrawing", d.querySelector("#mixv").textContent === "70%" && d.querySelector('[data-s="mix"]').value === "70");
  click('[data-a="smode"][data-id="off"]');
  clickText('[data-a="ssave"]', "Save season scores");
  ok("saving shows each season's score with best and weakest marked", await waitFor(() => text().includes("Season 1 5 / 5, best") && text().includes("Season 2 3 / 5, weakest"), "season chips"));
  ok("season headers carry the same badges", text().includes("Best season") && text().includes("Weakest"));
  ok("with counting off the show's own score is unchanged", text().includes("do not change this show's score"));

  // equal scores prompt a tie-break, and the answer decides the best season
  click('[data-a="rateseasons"]'); await waitFor(() => d.querySelectorAll(".srow").length === 2, "reopen");
  click('[data-a="spick"][data-id="2|5"]');
  clickText('[data-a="ssave"]', "Save season scores");
  ok("two seasons tied at the top trigger one question", await waitFor(() => text().includes("Which season was better?") && text().includes("both scored 5 / 5"), "tie question"));
  clickText('[data-a="stie"]', "Season 2 was better");
  ok("the answer decides the best season", await waitFor(() => text().includes("Season 2 5 / 5, best") && !text().includes("Which season was better?"), "tie settled"));

  // letting seasons count changes the show's score, and is clearly labelled
  click('[data-a="rateseasons"]'); await waitFor(() => d.querySelectorAll(".srow").length === 2, "reopen again");
  click('[data-a="spick"][data-id="1|2"]'); click('[data-a="spick"][data-id="2|2"]');
  click('[data-a="smode"][data-id="seasons"]');
  ok("seasons-only mode previews the new score", await waitFor(() => d.querySelector("#spreview").textContent.includes("Counts as 2 / 5"), "seasons only preview"));
  clickText('[data-a="ssave"]', "Save season scores");
  ok("the panel explains how the show's score is worked out", await waitFor(() => text().includes("worked out from its season scores alone") && text().includes("counts as 2 / 5"), "explained"));
  ok("the show's headline score now follows the seasons", text().includes("2 / 5") && text().includes("Earlier ratings"));
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Stats");
  ok("stats show how your shows age", await waitFor(() => text().includes("How your shows age") && text().includes("Average score by season number") && text().includes("Season 1 (1 show)"), "aging panel"));
  // put it back so later checks see the show's own score
  d.querySelector(".logo"); await w.eval("go('library')"); await waitFor(() => d.querySelector('[data-a="lib"]'), "library chips");
  click('[data-a="lib"][data-id="completed"]'); await waitFor(() => d.querySelector(".lcard"), "completed cards");
  d.querySelector('[data-a="open"]').click(); await waitFor(() => d.querySelector('[data-a="rateseasons"]'), "show page again");
  click('[data-a="rateseasons"]'); await waitFor(() => d.querySelectorAll(".srow").length === 2, "reopen last");
  click('[data-a="smode"][data-id="off"]'); clickText('[data-a="ssave"]', "Save season scores");
  ok("switching counting off restores the show's own score", await waitFor(() => text().includes("do not change this show's score"), "off again"));

  // to-watch page with readiness
  click('.tab[data-id="search"]');
  await waitFor(() => d.querySelector("#q"), "search");
  setVal("#q", "night");
  await waitFor(() => text().includes("Night Ferry"), "ferry");
  clickText('[data-a="addshow"]', "Add to watch list");
  await waitFor(() => text().includes("In your library"), "added");
  clickText(".tab", "To watch");
  ok("to-watch shows still-airing badge", await waitFor(() => text().includes("Still airing (2 of 6 episodes out)"), "to-watch"));

  // ratings page
  ok("Ratings is a main tab, and no longer in the Profile menu", [...d.querySelectorAll("#tabs > .tab")].some(t => t.dataset.id === "ratings") && (clickText('[data-a="menu"]', "Profile"), !d.querySelector(".menu").textContent.includes("Ratings")));
  click('[data-a="menu"]');
  clickText(".tab", "Ratings");
  ok("it opens on Rankings, with the other sections one tap away", await waitFor(() => d.querySelector('[data-a="rtab"][data-id="ranks"]').getAttribute("aria-pressed") === "true" && text().includes("Scorecard") && text().includes("Arena") && text().includes("Favourites"), "ratings opens on rankings"));
  ok("a one-time tip explains the page, and Got it removes it", text().includes("Rankings lists your shows") && (click('[data-a="tipok"][data-id="ratings"]'), await waitFor(() => !text().includes("Rankings lists your shows"), "tip gone")));
  clickText('[data-a="rtab"]', "Scorecard");
  ok("scorecard section", await waitFor(() => text().includes("What matters to you"), "scorecard"));
  clickText('[data-a="rpreset"]', "Looks first");
  ok("preset changes importance", await waitFor(() => d.querySelector('[data-a="rpreset"][data-id="looks"]').getAttribute("aria-pressed") === "true", "preset"));
  click('[data-a="rweight"][data-id="cine|1"]');
  ok("importance level can be set per category", await waitFor(() => d.querySelector('[data-a="rweight"][data-id="cine|1"]').getAttribute("aria-pressed") === "true", "weight"));
  clickText('[data-a="rtab"]', "Rankings");
  ok("rankings list the rated show", await waitFor(() => text().includes("Harbour Lights") && /\/ 5/.test(text()), "rankings"));
  clickText('[data-a="rtab"]', "Arena");
  ok("arena says so when nothing is close", await waitFor(() => text().includes("No close calls to settle"), "arena empty"));
  clickText('[data-a="rtab"]', "Favourites");
  ok("favourites tab lists the episode", await waitFor(() => text().includes("Harbour Lights") && text().includes("S1E1"), "favs"));
  clickText('[data-a="rtab"]', "Scorecard");
  ok("old-shows path is offered, never forced", await waitFor(() => text().includes("The Counting never asks you to rate your old shows"), "old shows"));
  click('[data-a="seenpage"]');
  ok("already-watched search mode", await waitFor(() => d.querySelector("#q") && text().includes("Search for a show you watched before The Counting"), "seen search"));

  // add shows you have already watched, then rate them
  setVal("#q", "paper");
  await waitFor(() => text().includes("I have already watched it"), "paper result");
  clickText('[data-a="addseen"]', "I have already watched it");
  ok("asks how much you have seen", await waitFor(() => text().includes("How much of Paper Kingdoms have you seen?") && text().includes("Up to the end of season 2"), "seen modal"));
  clickText('[data-a="seenthru"]', "All of it");
  ok("returning show goes to watching, no rate prompt", await waitFor(() => text().includes("Paper Kingdoms with 6 episodes marked") && !text().includes("Rate it?"), "paper added"));
  setVal("#q", "very long"); await waitFor(() => text().includes("Very Long Show"), "long result");
  clickText('[data-a="addseen"]', "I have already watched it");
  await waitFor(() => text().includes("How much of Very Long Show"), "long modal");
  clickText('[data-a="seenthru"]', "All of it");
  ok("finished show asks for a rating", await waitFor(() => text().includes("You finished Very Long Show. Rate it?"), "long prompt"));
  clickText('[data-a="rateshow"]', "Rate now"); await waitFor(() => d.querySelector('[data-r="cine"]'), "sliders");
  clickText('[data-a="saverate"]', "Save rating"); await waitFor(() => text().includes("Rating saved"), "saved");
  clickText(".tab", "Library"); await waitFor(() => d.querySelector('[data-a="lib"]'), "library");
  click('[data-a="lib"][data-id="watching"]'); await waitFor(() => d.querySelector(".lcard h2") && d.querySelector(".lcard h2").textContent === "Paper Kingdoms", "watching tab");
  d.querySelector('[data-a="open"]').click(); await waitFor(() => d.querySelector("h1").textContent === "Paper Kingdoms", "paper page");
  clickText('[data-a="rateshow"]', "Rate this show"); await waitFor(() => d.querySelector('[data-r="cine"]'), "paper sliders");
  setVal('[data-r="cine"]', "1"); setVal('[data-r="writing"]', "1");
  clickText('[data-a="saverate"]', "Save rating"); await waitFor(() => text().includes("Rating saved"), "paper saved");

  // discover: locked below 3 ratings would say so; with 3 it ranks from your ratings
  clickText(".tab", "Discover");
  ok("discover ranks by your ratings", await waitFor(() => text().includes("Why here:") && text().includes("Versus the next pick:") && text().includes("How this is ranked"), "discover"));
  ok("discover shows tiers and rank numbers", text().includes("1. ") && /(Strong match|Good match|Worth a look)/.test(text()));
  const firstName = d.querySelector(".card h3").textContent;
  click('[data-a="dmode"][data-id="tmdb"]');
  ok("TMDB order is one click away", await waitFor(() => text().includes("Recommended because you finished") && !text().includes("Why here:"), "tmdb order"));
  click('[data-a="dmode"][data-id="you"]'); await waitFor(() => text().includes("Why here:"), "back to ranked");
  click('[data-a="ddismiss"]');
  ok("not interested removes the card for good", await waitFor(() => text().includes("Got it. That show will not be suggested again."), "dismissed"));
  click('[data-a="dadd"]');
  ok("add to watch list from discover", await waitFor(() => text().includes("to your watch list."), "added from discover"));

  // the arena: rounds of five, categories with counts, honest estimates
  await w.eval(`(async () => {
    const sc = v => Object.fromEntries(["writing","acting","cine","edit","sound","dir"].map(k => [k, v]));
    for (const id of [500, 501, 502, 503]) { await api("/api/shows", "POST", { tmdb_id: id, status: "watching" }); await api("/api/ratings", "POST", { show_id: id, mode: "card", scores: sc(5) }); }
    await api("/api/ratings/profile", "POST", { same_genre: false });
  })()`);
  await w.eval("S.rt.tab = 'arena'; S.rt.arenaScope = 'all'; S.rt.round = { n: 0, total: 5, active: false, done: false }; go('ratings')");
  ok("arena offers a round, not a pile of homework", await waitFor(() => text().includes("Ready when you are") && /roughly \d+ questions?/.test(text()) && text().includes("Start a round of 5"), "arena start"));
  ok("Overall is the starting view and the six categories are one tap away, without scary numbers", d.querySelector('[data-a="rascope"][data-id="overall"]').getAttribute("aria-pressed") === "true" && d.querySelectorAll('[data-a="rascope"]').length === 7 && !/Overall \(\d+\)/.test(text()));
  ok("a switch limits the arena to settling the top three", d.querySelector('[data-a="rtop"]') !== null && text().includes("Only settle my top three"));
  ok("the screen explains what it will and will not ask", text().includes("4 out of 5 or higher") && text().includes("already settle") && text().includes("never have to finish"));
  click('[data-a="rstart"]');
  ok("a round starts at pick 1 of 5", await waitFor(() => text().includes("Pick 1 of 5") && text().includes("which is better?"), "pick 1"));
  clickText('[data-a="rcmp"]', "is better");
  ok("answering moves to pick 2", await waitFor(() => text().includes("Pick 2 of 5") || text().includes("Round complete") || text().includes("All settled here"), "pick 2"));
  click('[data-a="rstop"]');
  ok("a round can be ended early", await waitFor(() => text().includes("Ready when you are") || text().includes("No close calls"), "round stopped"));
  click('[data-a="rascope"][data-id="cine"]');
  ok("choosing one category narrows the view", await waitFor(() => d.querySelector('[data-a="rascope"][data-id="cine"]').getAttribute("aria-pressed") === "true", "cine view"));
  clickText('[data-a="rstart"]', "Start a round"); await waitFor(() => text().includes("Pick 1 of 5"), "cine pick");
  for (let i = 0; i < 6 && !text().includes("Round complete") && !text().includes("All settled here"); i++) { clickText('[data-a="rcmp"]', "is better"); await sleep(250); }
  ok("a round ends with a clear summary and a way out", await waitFor(() => (text().includes("Round complete") || text().includes("All settled here")) && text().includes("Done for now"), "round done"));
  click('[data-a="rstop"]');
  await w.eval("S.rt.tab = 'card'; S.rt.arenaScope = 'all'");

  // light and dark mode
  const htmlTheme = () => d.documentElement.getAttribute("data-theme");
  const before = htmlTheme();
  click('[data-a="themeflip"]');
  ok("the round button switches mode and applies it at once", await waitFor(() => htmlTheme() === "dark" || htmlTheme() === "light", "theme applied") && htmlTheme() !== before);
  const chosen = htmlTheme();
  click('[data-a="themeflip"]');
  ok("and switches back", await waitFor(() => htmlTheme() !== chosen && htmlTheme() !== null, "theme flipped back"));
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Settings");
  ok("settings offers Match my device, Light and Dark", await waitFor(() => text().includes("Appearance") && text().includes("Match my device") && d.querySelector('[data-a="settheme"][data-id="dark"]'), "appearance panel"));
  click('[data-a="settheme"][data-id="dark"]');
  ok("choosing Dark sticks", await waitFor(() => htmlTheme() === "dark" && d.querySelector('[data-a="settheme"][data-id="dark"]').getAttribute("aria-pressed") === "true", "dark chosen"));
  click('[data-a="settheme"][data-id="system"]');
  ok("Match my device removes the override", await waitFor(() => htmlTheme() === null, "system"));
  ok("the product name is The Counting", d.title === "The Counting" && d.querySelector(".logo").textContent.includes("The Counting"));

  // phone access
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Settings");
  ok("settings has a phone access panel that is off by default", await waitFor(() => text().includes("Use on my phone") && d.querySelector('[data-a="lanon"]').getAttribute("aria-checked") === "false", "lan panel"));
  ok("it says paired phones cannot touch the computer", text().includes("cannot open folders, make backups, export, or change your TMDB key"));
  click('[data-a="lanon"]');
  ok("turning it on shows the address and a Pair button", await waitFor(() => d.querySelector('[data-a="lanpair"]') !== null && text().includes("Listening at") && text().includes("No phones paired yet"), "lan on"));
  click('[data-a="lanpair"]');
  ok("pairing shows a QR code, a six-digit code and the expiry", await waitFor(() => d.querySelector(".qrbox svg") !== null && /^\d{6}$/.test(d.querySelector(".pin").textContent) && text().includes("expires in 10 minutes"), "pair modal"));
  ok("the QR code is a real drawing with many cells", d.querySelector(".qrbox svg") !== null && d.querySelector(".qrbox svg").innerHTML.length > 800);
  clickText('[data-a="close"]', "Done");
  click('[data-a="lanon"]');
  ok("and it can be switched off again", await waitFor(() => d.querySelector('[data-a="lanpair"]') === null && d.querySelector('[data-a="lanon"]').getAttribute("aria-checked") === "false", "lan off"));

  // the self-check, from Settings
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Settings");
  ok("settings offers a self-check", await waitFor(() => d.querySelector('[data-a="selftest"]') !== null && text().includes("Run a self-check"), "self-check button"));
  click('[data-a="selftest"]');
  let waited = 0; while (!d.querySelector(".selfout") && waited++ < 400) await sleep(50);
  ok("it shows a copyable report", d.querySelector(".selfout") !== null && d.querySelector(".selfout").value.includes("The Counting self-check") && d.querySelector(".selfout").value.includes("PASS  Database"));
  ok("and says whether everything required passed", text().includes("Everything required passed."));
  // profile menu: stats, log, backups
  clickText('[data-a="menu"]', "Profile");
  ok("profile menu lists pages", await waitFor(() => d.querySelector(".menu") && text().includes("Watch log") && text().includes("Backups and data") && text().includes("Settings"), "menu"));
  clickText('[data-a="nav"]', "Stats");
  ok("stats page", await waitFor(() => text().includes("episodes watched") && text().includes("Hours by genre"), "stats"));
  ok("stats notes undated bulk marks", text().includes("bulk-marked episodes have no date"));
  ok("stats lead with derived views, not a list of shows", text().includes("Where you watch") && text().includes("How you rate, by genre") && text().includes("Hours by decade") && text().includes("When you watch"));
  ok("hours by show is now a short 'Most watched' list at the end", text().includes("Most watched shows") && !text().includes("Hours by show"));
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Watch log");
  ok("log shows bulk and rewatch entries", await waitFor(() => text().includes("bulk") && text().includes("rewatch"), "log"));
  clickText('[data-a="menu"]', "Profile"); clickText('[data-a="nav"]', "Backups and data");
  ok("backups page", await waitFor(() => text().includes("Back up now"), "data page"));
  click('[data-a="backupnow"]');
  ok("manual backup listed", await waitFor(() => text().includes("-manual.db"), "backup row"));
  clickText('[data-a="restore"]', "Restore");
  ok("restore asks for confirmation", await waitFor(() => text().includes("Restore this backup?"), "restore modal"));
  clickText('[data-a="close"]', "Cancel");
  ok("modal closes", await waitFor(() => !text().includes("Restore this backup?"), "closed"));

  // remove keeps history
  clickText(".tab", "Library"); await waitFor(() => d.querySelector('[data-a="lib"]'), "chips");
  click('[data-a="lib"][data-id="completed"]'); await waitFor(() => d.querySelector(".lcard"), "cards");
  const victim = d.querySelector(".lcard h2").textContent;
  d.querySelector('[data-a="open"]').click();
  await waitFor(() => d.querySelector('[data-a="remove"]'), "remove btn");
  click('[data-a="remove"]');
  ok("remove asks first", await waitFor(() => text().includes("Your watch history is kept"), "remove modal"));
  clickText('[data-a="removeyes"]', "Remove from library");
  ok("removed show leaves library", await waitFor(() => d.querySelector("h1").textContent === "Library", "back to library"));
  click('[data-a="lib"][data-id="completed"]');
  ok("removed show is gone from completed", await waitFor(() => !d.querySelector(".lcard h2") || ![...d.querySelectorAll(".lcard h2")].some(e => e.textContent === victim), "gone"));

  console.log(failed ? "\n" + failed + " FAILED" : "\nALL BROWSER TESTS PASSED");
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log("ERROR " + e.stack); process.exit(1); });
