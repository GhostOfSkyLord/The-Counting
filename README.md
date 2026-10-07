# The Counting

A personal TV show tracker. Your lists and progress stay on your computer. Show details come from TMDB.

## What is in The Counting

- Add shows from TMDB, keep a library (a poster-first grid with one square per episode) and a watch list
- Mark episodes, with prompts for skipped episodes and rewatches, and a "Seen up to here" shortcut
- Spoiler curtain: thumbnails and synopses stay hidden until you finish the previous episode; synopses are fogged until clicked
- Per-show display rules: hide titles, absolute numbering, count specials
- "Ready to binge" badges and time commitment on the watch list
- **Ratings:** a weighted scorecard (writing, acting and casting, cinematography, editing and pacing, sound and music, direction) where you set how much each matters, or a simple 1-5 / 1-10 score. Optional gut score. Re-rating keeps a history and the latest counts. Changing your importance settings recalculates every final score.
- **Rankings and arena:** overall and per-category rankings. When two top-scoring shows are tied or within half a point, the arena asks which is better, five questions at a time. It opens on Overall, skips pairs your earlier answers already settle, and by default stops once your top three are in order. Each category is one tap away. Your answers break ties and can overturn a small gap.
- **Season ratings:** score each season of a multi-season show, see your best and weakest seasons, settle tied bests with one question, and (only if you choose) let the seasons count toward the show's score, either blended in by a percentage or on their own
- **Favourite episodes** (watched episodes only)
- **Discover:** suggestions from TMDB's recommendation links, **ranked by your own ratings** once you have rated 3 shows, with a plain-language "why here" and "versus the next pick" for each. A toggle shows TMDB's own order instead. "Not interested" removes a show for good.
- **Shows you watched before The Counting:** never forced. Add one with "I have already watched it", say how much you saw (episodes are marked without invented dates), and rate it if you like.
- Stats and a watch log (Profile menu)
- Automatic local backups, restore, and a plain-file export/import that includes ratings, comparisons and favourites
- Windows and Mac (see below)
- Coming later: alternate episode orderings, using dropped shows as a negative signal in Discover, custom rating categories, arena duels ranked with a Glicko-style engine

## Run it (Windows)

1. **One time:** double-click `setup.bat`. It installs the small window component The Counting uses.
2. Double-click `The Counting.pyw`. No console window appears, only The Counting.
3. On first launch, paste your free TMDB API key. Create one at themoviedb.org under Settings, then API.

If `The Counting.pyw` opens in a text editor instead of running, right-click it, choose Open with, then Python (pythonw).
If the window component is not installed, The Counting opens in Microsoft Edge's app mode instead.

## Make a normal app (optional)

Double-click `build.bat`. When it finishes, your app is `dist\The Counting\The Counting.exe`. Keep the whole `The Counting` folder together and make a desktop shortcut to the exe.

Windows may show "Windows protected your PC" the first time, because the app is not code-signed. Choose More info, then Run anyway. Some antivirus tools flag any newly built app; the folder build used here triggers this less often than a single-file exe.

No Python? Upload this project to a GitHub repository and run the "Build The Counting" workflow in the Actions tab (`.github/workflows/build.yml`), then download the result.

## Run it on a Mac

You need Python 3 (from python.org). In Terminal, from this folder:

```
python3 -m pip install -r requirements.txt
python3 run_thecounting.py
```

To make a real app instead, run `./build.sh`. It creates `dist/The Counting.app`.

## Ready-made apps for Windows and Mac, no Python needed

Upload this project to a GitHub repository. The file `.github/workflows/build.yml` then builds The Counting on GitHub's own Windows and Mac machines, after running the tests on Windows, Mac and Linux:

1. Open the repository's **Actions** tab, choose **Build The Counting**, press **Run workflow**. When it finishes, the downloads are under **Artifacts**.
2. Or create a release with a tag such as `v0.2.1`. The three downloads are attached to the release page, which is easy to share.

You get three files: `TheCounting-windows.zip`, `TheCounting-mac-apple-silicon.zip` (Macs from late 2020 onward with an M-series chip) and `TheCounting-mac-intel.zip` (older Intel Macs). To check a Mac: Apple menu, About This Mac. It says Chip (Apple) or Processor (Intel).

Send friends **GETTING_STARTED.md** with the right file.

### What Mac users will see

The app is not signed with a paid Apple Developer certificate, so on macOS 15 and newer the first launch is blocked with a warning. It is a one-time step per Mac: dismiss the warning, open System Settings, Privacy & Security, scroll down to Security, click **Open Anyway** next to The Counting, and enter the Mac's password. The old right-click shortcut no longer works on these versions. Removing this step needs a paid Apple Developer membership and notarization, which is worth considering only if The Counting is shared widely.

The Windows app shows a "Windows protected your PC" screen on first launch for the same reason. Choose More info, then Run anyway.

## Where things are

The Counting keeps everything in one folder. Open it from Settings, Help, Open The Counting's data folder.

| System | Location |
|---|---|
| Windows | `%APPDATA%\The Counting` |
| Mac | `~/Library/Application Support/The Counting` |

If you used the app under its earlier name (Tally), the old folder is moved to the new name the first time you open this version, with your shows, history, ratings and backups inside. If the move ever fails, the old folder simply keeps being used, so nothing is lost.

| Item | Name |
|---|---|
| Database | `tally.db` (the file name is unchanged so existing backups keep working) |
| Backups | `backups/` (or the folder you choose in Settings) |
| Exports | `exports/` |
| Cached artwork | `imgcache/` |
| Log file | `thecounting.log` (look here if something goes wrong) |

## Look and feel

Two modes, light and dark. The round button at the top right switches them, and Settings, Appearance can also set "Match my device". The choice is saved and applied before the page draws, so there is no flash of the wrong colours.

The palette comes from four places:

- **Bauhaus** for the structure: flat colour blocks, hard edges, and Kandinsky's pairing of yellow triangle, red square and blue circle, which is the logo.
- **Squid Game** for the accents: its pink and teal, and its guards' circle, triangle and square, which are the same three shapes.
- **Japanese woodblock prints** for the ground and the pigments: washi paper by day, night indigo by night, indigo, vermilion and ochre, and the seigaiha wave pattern on the welcome screen.
- **Belle Epoque** for the frame: the gold band under the masthead, and the dusty mauve behind the spoiler fog.

Headings use Jost (a Futura-style geometric typeface, bundled with the app under the SIL Open Font License) and text uses your system font. Progress is drawn as separate counting blocks. All text colours meet the WCAG AA contrast ratio in both modes, and a test checks this.

## Backups

- A snapshot is made when The Counting opens (if the newest is over 6 hours old) and when it closes after changes. The newest 10 are kept.
- Profile, then Backups and data: back up now, open the folder, restore, export, import.
- Restoring saves a copy of your current data first, and keeps your API key.
- Point the backup folder at a cloud-synced folder in Settings if you want copies off this computer.

## Tests

`python -m unittest discover -s tests -p "test_*.py"` runs the backend tests against a fake TMDB (including the upgrade of an older database and a real secure-connection test). `tests/e2e.js` clicks through the real UI (needs Node and jsdom); `tests/run_test_server.py` starts the app for it.

## Troubleshooting

### "Could not reach TMDB: the connection was refused or reset"

Something between your PC and TMDB is cutting the connection. Your key is not the problem. Check the version number at the bottom of The Counting: you need **0.1.1 or newer** for the fixes below.

**If Edge can open https://api.themoviedb.org but The Counting cannot**, the usual cause is DNS. Edge can look addresses up over an encrypted "secure DNS" service, while programs like The Counting ask Windows, and some networks give Windows an address that leads to a blocked server. From version 0.1.1, The Counting handles this itself: if the normal connection fails, it asks Cloudflare (1.1.1.1) or Google (8.8.8.8) for the address, the way Edge does, and connects there with full certificate checking. This is on by default (Settings, "Use secure DNS if needed"). Run the Connection check in Settings to see which route works.

If that is not enough, try these in order:

1. **Change your Windows DNS.** Settings, Network and internet, your Wi-Fi or Ethernet, Hardware properties, DNS server assignment, Edit, Manual, turn on IPv4, Preferred DNS `1.1.1.1`, Alternate DNS `8.8.8.8`, Save. Reopen The Counting.
2. **Try your phone's hotspot.** If The Counting works there, your home provider is the blocker.
3. **Check for a proxy.** The Connection check reports proxy settings. If a proxy is set that Edge uses through an automatic script, The Counting may not follow it.
4. **Allow The Counting through security software.** In Windows Security, Firewall and network protection, Allow an app through firewall, allow `pythonw.exe` (or `The Counting.exe` if you built the app). Some antivirus tools inspect secure connections; add an exception for The Counting, or briefly pause its web protection to test.
5. **Use a VPN**, if your provider blocks the connection itself.

The Counting also tries a second TMDB address (api.tmdb.org) automatically, and remembers which route works.

Posters come from a separate TMDB address and use the same fallbacks. If they are still blocked, shows appear with initials instead of artwork.

### Other problems

- **A message says The Counting is already running:** close the other copy (Task Manager on Windows, Activity Monitor on Mac).
- **Blank or missing window:** install Microsoft Edge WebView2 (already on most Windows 10 and 11 PCs) or run `setup.bat` again.
- **"TMDB rejected the API key":** paste the key again in Settings. Either the short API Key or the long Read Access Token works.
- **"This window lost contact with The Counting's engine":** the window is open but the small local server behind it stopped answering. Close The Counting and open it again. Version 0.1.2 makes this much less likely (bigger connection queue, a self-restarting server loop, and no early shutdown when the window is minimised). If it still happens, go to Settings, Help, Open The Counting's data folder, and look at the end of `thecounting.log` (and `crash.log` if it exists). The log records how the window was opened and why the engine stopped.


## Use it on your phone

Settings has a "Use on my phone" panel. On an iPhone, pair in Safari first and then use Add to Home Screen. Switch it on, press "Pair a phone", and scan the QR code with a phone on the same Wi-Fi (or type the six-digit code). The phone then shows your computer's copy of The Counting in phone layout. It works in any phone browser, so it covers Android and iPhone alike, and "Add to Home Screen" gives it an icon. It is off by default, every phone must be paired, a paired phone cannot touch folders, backups, exports or your TMDB key, and you can forget a phone at any time. It uses plain HTTP, so use it on your home Wi-Fi, not public Wi-Fi. The computer must be on for the phone to work.


## First-time guide

After you save your TMDB key, The Counting offers a two-minute tour, and the top of your Library shows a Getting started list that ticks itself as you try things. Short one-time tips explain Ratings, the arena, Discover, Stats and the show page. All of it can be skipped, hidden, or brought back from Settings, Help.


## Building the Windows and Mac apps in the cloud, and checking them

See `CLOUD_BUILD.md`. You do not need a Mac: GitHub's own machines build the apps and then run each one's built-in self-check. Anyone can also run a self-check from Settings, Help, or with `The Counting --selftest results.json`.
