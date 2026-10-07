// A phone, simulated: pairs with the running app over the home-network server and uses it. Usage: node e2e_phone.js <desktop url>
const { JSDOM, CookieJar } = require(process.env.JSDOM_PATH || "jsdom");
const desktop = process.argv[2];
let failed = 0;
const ok = (n, c) => { console.log((c ? "ok   " : "FAIL ") + n); if (!c) failed++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // the computer: set up a key, switch phone access on, ask for a pairing code
  const dd = await JSDOM.fromURL(desktop, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, w.location.href), o); w.scrollTo = () => {}; } });
  await sleep(600);
  const tok = dd.window.document.querySelector('meta[name="tally-token"]').content;
  const api = async (p, b) => (await fetch(new URL(p, desktop), { method: b ? "POST" : "GET", headers: { "X-Tally-Token": tok, "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined })).json();
  await api("/api/settings/key", { key: "goodkey123" });
  await api("/api/shows", { tmdb_id: 100, status: "watching" });
  const st = await api("/api/lan/enable", { on: true });
  ok("phone access is on", st.running && st.urls.length > 0);
  const pairing = await api("/api/lan/pair", {});
  const base = st.urls[0];

  // a phone with no pairing sees only the pairing page
  const stranger = await fetch(base);
  ok("an unpaired phone is turned away", stranger.status === 403 && (await stranger.text()).includes("Pair this device"));

  // a phone that scans the QR code
  const jar = new CookieJar();
  const phone = await JSDOM.fromURL(pairing.links[0], { cookieJar: jar, runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse(w) {
    w.fetch = async (u, o = {}) => { const url = new URL(u, w.location.href); const c = jar.getCookieStringSync(url.href); return fetch(url, { ...o, headers: { ...(o.headers || {}), Cookie: c } }); };
    w.scrollTo = () => {}; w.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
  } });
  const d = phone.window.document, w = phone.window;
  const text = () => d.body.textContent.replace(/\s+/g, " ");
  const waitFor = async (fn, label) => { for (let i = 0; i < 80; i++) { try { if (fn()) return true; } catch (e) {} await sleep(50); } console.log("   (timeout: " + label + ")"); return false; };
  ok("the paired phone loads the app", await waitFor(() => d.querySelector("h1") && d.querySelector("h1").textContent === "Library", "library on phone"));
  ok("it sees the show added on the computer", text().includes("Harbour Lights"));
  ok("the phone knows it is remote", w.eval("S.app.remote") === true);
  ok("a phone that connects to existing data is not offered the tour", w.eval("S.guide.state.tour") === "skipped" && d.querySelector(".tour") === null && !text().includes("two-minute tour"));
  ok("the phone keeps its own guide state in the browser", JSON.parse(w.localStorage.getItem("tc-guide")).tour === "skipped");

  // use it
  d.querySelector('[data-a="mark"]').click();
  ok("marking an episode works from the phone", await waitFor(() => text().includes("1 of 8 aired episodes watched"), "mark on phone"));
  const lib = await api("/api/library?status=watching");
  ok("and shows up on the computer", lib.shows[0].progress.watched === 1);

  // what is hidden or limited on a phone
  w.eval("go('settings')");
  ok("settings on a phone has no key, backup or folder controls", await waitFor(() => text().includes("This phone") && !text().includes("TMDB API key") && !text().includes("Backup folder") && !text().includes("Use on my phone"), "phone settings"));
  d.querySelector('[data-a="menu"]').click();
  ok("the Profile menu has no Backups and data page", await waitFor(() => d.querySelector(".menu") !== null && !d.querySelector(".menu").textContent.includes("Backups and data"), "phone menu"));
  d.querySelector('[data-a="settheme"][data-id="dark"]') || d.querySelector('[data-a="menu"]').click();
  w.eval("setTheme('dark')");
  ok("a phone chooses its own colour mode without changing the computer's", await waitFor(() => d.documentElement.getAttribute("data-theme") === "dark", "phone dark") && (await api("/api/state")).theme === "system");

  // forget the phone on the computer: it is locked out at once
  const devs = (await api("/api/lan")).devices;
  ok("the computer lists the paired phone", devs.length === 1);
  await api("/api/lan/forget", { id: devs[0].id });
  const after = await fetch(base, { headers: { Cookie: jar.getCookieStringSync(base) } });
  ok("forgetting it locks the phone out", after.status === 403);
  console.log(failed ? "\n" + failed + " FAILED" : "\nALL PHONE TESTS PASSED");
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log("ERROR " + e.stack); process.exit(1); });
