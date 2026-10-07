# Changelog

## 0.7.1
Mac and iPhone groundwork.
- **A built-in self-check.** Settings, Help, "Run a self-check" tests that this copy has everything it needs (its files, database, local server, secure-connection certificates, window component, and a secure connection to TMDB) and gives a report you can copy. It never touches your shows. The same check runs from the command line as `The Counting --selftest results.json`.
- **The cloud build now tests the apps it makes.** After building for Windows, both kinds of Mac, and Linux, the workflow starts each finished app with the self-check and shows the result, so a Mac or Windows build can be verified without owning that computer. It also records how each Mac app is signed and which macOS version it needs, and adds a SHA256SUMS.txt to releases. See CLOUD_BUILD.md.
- **A fix aimed at a classic Mac problem.** A packaged Mac app often finds no trusted certificates, which would block every connection to TMDB. When none are found, The Counting now uses a bundled set (certifi). The builds include it.
- **iPhone wording corrected.** On an iPhone, pair in Safari first, then use Add to Home Screen. The icon copies the pairing once, at that moment.

## 0.7.0
- **A first-time guide.** Three layers, none of them in the way:
  - **A welcome and a two-minute tour,** offered once after the TMDB key is saved. Eight cards cover the squares, adding shows, the spoiler curtain, ratings and seasons, rankings and the arena, Discover and stats, and backups and your phone. Each picture is drawn with the app's own screens and sample data. Skip it any time. Use the arrow keys or Next and Back, and replay it from the Profile menu or Settings.
  - **A Getting started list** at the top of your Library. It ticks itself as you do real things (add a show, mark an episode, rate, favourite an episode, visit the arena, see Discover, pair a phone), and "Show me" takes you to the right place and highlights the button. Hide it whenever you like.
  - **One-time tips** on Ratings, the arena, Discover, Stats and your first show page, each with a "Got it".
- **Ratings is now a main tab** (Library, To watch, Discover, Ratings, Add show) and opens on Rankings. Scorecard, Arena and Favourites are one tap away. Stats, Watch log, Settings and Backups stay under Profile. On a phone the tab labels are shortened so all six fit.
- If you already have shows when you upgrade, you are not treated as new: the tour is not offered, and your tips and checklist are marked as seen. Settings, Help, has "Show the tour again" and "Bring back tips and the checklist". A phone keeps its own guide progress in its browser.

## 0.6.0
- **Use it on your phone (Android and iPhone).** Settings has a new "Use on my phone" panel. Turn it on, press "Pair a phone", and scan the QR code with the phone's camera (or type the six-digit code). The phone then shows The Counting from your computer's copy, with the same screens in phone layout. Your computer must be on and on the same Wi-Fi.
- **Safe by default.** It is off until you switch it on. Every phone must be paired first; pairing codes work once and expire in ten minutes; five wrong codes cancel all open pairings. Only devices on your local network are accepted, and a made-up host name is refused. A paired phone can track, rate, search and browse, but cannot open folders, make or restore backups, export or import, or change your TMDB key or settings on the computer. You can forget a phone at any time and it is locked out at once. Only a hash of each phone's secret is stored.
- It uses plain HTTP, which is fine on your own home Wi-Fi but not on public Wi-Fi. Windows may ask whether to allow network access the first time: choose private networks only.
- **Add to Home Screen** gives it an icon and full-screen look on both Android and iPhone. A phone picks its own light or dark mode. (On an iPhone you may need to pair again from the Home Screen icon.)

## 0.5.0
Design refinement.
- **Library:** big poster cards in a grid that fills the screen (five or more across on a wide monitor, two on a phone). Each card shows the poster, the next episode, one **square per episode** (teal watched, a red outline for the next one, hatched for not yet aired) and a Mark watched button.
- **Show page:** the artwork leads. The landscape backdrop runs across the top and fades into the page, with the full poster overlapping it (if a show has no backdrop, its poster is enlarged, blurred and faded instead). Episodes come first, with rating, season scores, display rules and cast in a side column on wide screens (below the episodes on a phone). Display rules and cast fold away until you want them. The one-square-per-episode overview sits beside the poster, and clicking a square jumps to that episode. The episode to watch next is marked.
- **Colours with one job each:** teal means watched or done, a red outline means the next episode, blue is for things you can press and for charts, yellow marks highlights (ready, best season), pink is for favourites, and mauve is for spoilers. Placeholder posters use four calm colours instead of six loud ones. The completion suggestion is a calm panel with a yellow edge, not a yellow block.
- **Desktop width:** pages use up to 1320 pixels. Stats flow into columns, Settings and Backups use two columns, and the Discover and To watch lists use as many columns as fit.
- **Quieter edges:** panels use thinner outlines. Hard shadows remain only on main buttons, menus and windows.
- Larger episode thumbnails, and larger posters in lists.

## 0.4.0
- **Season ratings.** Shows with more than one season get a "Rate seasons" button. Tap a score for each season you remember (1-5, or 1-10 if that is your rating style); seasons you skip are left out. Each season header then shows its score, with **Best season** and **Weakest** marked.
- **Tied best seasons** trigger one question, "Which season was better?", and your answer decides which is called your best.
- **Optional effect on the show's score.** Off by default, so nothing changes until you choose. *Blend* mixes the seasons' average (weighted by episode count) into the show's own score by a percentage you pick; *Seasons only* works the show's score out from its seasons alone. A live preview shows the result before you save, and the show page explains how its score was reached. Rankings, Discover, the arena and stats all use the score that counts, and rankings note "Includes your season scores".
- **Stats:** a new "How your shows age" panel: how many of your shows got better, held steady or got worse from first to latest scored season, and your average score by season number.
- Season scores keep a history like show ratings. They are included in exports, backups and restores, and older exports and databases upgrade cleanly.

## 0.3.2
- **Arena is much lighter.** It opens on Overall, only asks about shows you scored 4 out of 5 or higher, skips any pair your earlier answers already settle (if A beat B and B beat C, it will not ask about A and C), and by default stops once your top three are in order. Questions come in rounds of five, you can stop any time, and the screen says "roughly N questions in all" instead of a long list. Each of the six categories is one tap away. In a test with seven rated shows, the old arena would have asked about 41 pairs; the new one needs 1 to 12 depending on how bunched your scores are.
- **Synopsis:** episodes now show a small "Reveal synopsis" line that opens a clean box under the episode (and "Hide synopsis" closes it), instead of a blurred block of text.
- **Stats:** hours by show is now just a "Most watched" top five at the bottom. New: hours by network, hours by decade, your average rating by genre, and which days of the week you watch.

## 0.3.1
- Arena matchups are found much faster on large libraries.
- Added TESTING.md and this changelog.

## 0.3.0
- Renamed to **The Counting**. Your data folder is moved to the new name automatically on first launch.
- Light and dark mode (round button at the top right, or Settings, Appearance).
- New look: Bauhaus blocks and shapes, Japanese woodblock colours, Squid Game's pink and teal, a Belle Epoque gold band. Jost typeface bundled for offline use.

## 0.2.1
- Mac support: Mac data folder, Mac dialogs, "open folder" on Mac, and a cloud build for Windows and both kinds of Mac.

## 0.2.0
- Ratings: weighted scorecard or simple 1-5 / 1-10, rating history, rankings, arena (ties and near-ties), favourite episodes.
- Discover: suggestions ranked from your own ratings, with "why here" explanations.
- "I have already watched it" for shows from before the app.

## 0.1.2
- The window no longer loses contact with the engine (bigger connection queue, self-restarting server loop, no early shutdown when minimised).
- Settings, Help, Open the data folder.

## 0.1.1
- Secure-DNS fallback for networks where TMDB's address lookup leads to a blocked server.
- Connection check in Settings; automatic second TMDB address.

## 0.1.0
- First version: library, watch list, episode tracking with prompts, spoiler curtain, display rules, stats, watch log, automatic backups, export and import.
