# Testing The Counting

Thank you for trying it. This page covers how to start it, what to try, what a good result looks like, how to send me problems, and how to update.

## 1. Before you start (two minutes, worth doing)

If you used the app before it was renamed (when it was called Tally), your data lives in `%APPDATA%\Tally`.
**First, close the old app, then copy that whole folder somewhere safe** (for example to your Desktop). The new version moves it to `%APPDATA%\The Counting` on first launch, but a spare copy costs nothing.

## 2. Start it (Windows)

1. Unzip this package into a **new folder**. Do not unzip over the old one: the old launcher files would still be there and cause confusion. Your data is kept elsewhere, so an old folder can simply be deleted later.
2. Double-click **setup.bat** once. It installs the small window component.
3. Double-click **The Counting.pyw**. A window opens. No black console window should appear.
4. The version number is at the bottom of every page. This package is **0.7.1**.

If the window does not open, see "If something goes wrong" below.

## 3. What to try

Please go through these in any order, and note anything that feels slow, confusing, or wrong.

**Setup**
- First launch asks for your TMDB key. Paste it. If it fails, run the connection check on that screen.
- Check that your old shows, progress and ratings are all still there.

**Everyday use**
- Add a show you know. Mark an episode. Mark a later one and answer the "mark earlier episodes too?" prompt.
- Tap an already-watched episode and try the rewatch prompt.
- Use "Seen up to here" on a long show.
- Open a synopsis (it should be fogged until you click it) and look at an episode you have not reached (it should stay hidden).
- Try "Hide episode titles" and "Show absolute numbering" on a show.

**Lists**
- Mark a show completed and rate it. Re-rate it and check the earlier rating appears under "Earlier ratings".
- Discover: check the order and the "why here" lines make sense to you. Try the "TMDB order" toggle.
- Ratings, Arena: it opens on Overall and offers rounds of five. Try a round, then try a category chip, and the switch that limits it to your top three. Tell me whether the number of questions now feels reasonable.
- Open a synopsis with "Reveal synopsis" and close it again.
- **Season ratings:** on a show with several seasons, press "Rate seasons" and score a few. Check the Best season and Weakest badges on the season headers. Give two seasons the same top score and see whether the "Which season was better?" question feels worth asking.
- Try the "Should these scores change the show's score?" choices (No, Blend, Seasons only) and watch the preview. Then check that the show page, the library card and the rankings show the score you expect. Set it back to No if you do not like it.
- Stats: look at the network, decade, rating-by-genre, day-of-week and "How your shows age" views and tell me which are useful and which are not.
- Favourite a couple of episodes.

**Look and feel (new in 0.5.0, please look hard at these)**
- Library: posters should be large and the grid should fill your screen. Check the squares under each poster make sense: teal for watched, a red outline for next, hatched for not aired.
- Open a show: does the artwork at the top look good, with the poster overlapping it? Try a few shows, including an old or obscure one with poor artwork. Is the poster ever cropped badly? Does it look good in both light and dark?
- On the show page, are the episodes easy to reach, and do you find the rating and display rules where you expect? Click one of the small squares near the top: it should jump to that episode.
- Does any screen still feel crowded or empty on your monitor? Tell me the screen and roughly your screen size.
- Do the colours now feel calmer? Is each one doing a clear job?

**Look and feel (general)**
- Switch light and dark with the round button. Check text is readable everywhere and nothing looks broken.
- Resize the window narrow, like a phone. The navigation moves to the bottom.

**Self-check (new in 0.7.1)**
- Settings, Help, "Run a self-check". Everything required should pass. If something fails or warns, copy the report and send it to me. A warning on "Reaching TMDB" can simply mean no internet or a blocked connection.
- On a new computer (especially a Mac), run it first. It is the quickest way to see what is wrong.

**First-time guide (new in 0.7.0)**
- If you already have shows, the guide stays out of your way. To see it as a newcomer would: Settings, Help, then "Bring back tips and the checklist", and "Show the tour again". Or start from a clean data folder.
- Take the tour. Is each card clear? Is anything wrong, missing, too long, or too much? Do the arrow keys and Escape behave?
- Use the Getting started list: press "Show me" on each item and check it takes you to the right place and the items tick themselves as you do them.
- Look at the one-time tips on Ratings, the arena, Discover, Stats and a show page. Are they useful or annoying?
- Ratings is now a main tab. Does that feel right? On a phone, do all six tabs fit and read clearly?

**Phone (new in 0.6.0)**
- On the computer: Settings, then "Use on my phone", switch it on, press "Pair a phone". Windows may ask about network access: choose private networks.
- On the phone, on the same Wi-Fi, scan the QR code. If it does not scan, open the address shown and type the six-digit code.
- Use it for a while: mark episodes, rate, search. Check that what you do on the phone shows on the computer and the other way round.
- Try "Add to Home Screen". On an iPhone use Safari, and pair BEFORE adding it: the Home Screen icon gets a one-time copy of the pairing. If the icon asks to pair again, tell me.
- Check that Settings on the phone has no key, backup or folder controls, and that a phone can have its own light or dark mode.
- On the computer, press Forget next to the phone. The phone should be locked out straight away.
- Tell me about anything that does not connect, and which phone and computer you used.

**Safety net**
- Profile, Backups and data: press **Back up now**, then look at the list. Close the app and reopen it: a backup should also be made on close if anything changed.
- Press **Export my data** and open the file in a text editor to see what is in it.

## 4. What good looks like

- Pages open instantly. Library, stats, ratings and the arena should all feel immediate, even with a few hundred shows (I measured under about a tenth of a second with 600 shows on a test machine, not including your internet speed).
- **Adding a show** takes a second or two, depending on TMDB and your connection. A show with many seasons takes a little longer.
- Posters can take a moment to appear the first time (they are downloaded once, then kept on your computer). If your network blocks TMDB's image address you will see coloured tiles with initials instead. That is expected.
- Closing and reopening never loses anything.

## 5. If something goes wrong

1. **Settings, Help, Open The Counting's data folder** opens the folder where everything lives.
2. Look at the end of **thecounting.log**. If there is a file named **crash.log**, look at that too.
3. Send me: what you were doing, what you expected, what happened, the version number, and the last 15 or so lines of `thecounting.log`. A screenshot helps.

If the window will not open at all, the data folder is `%APPDATA%\The Counting` (paste that into the Windows Explorer address bar). A dialog box should also appear explaining the problem.

## 6. Updating

When I send a new version:
1. Close The Counting.
2. Unzip the new package into a **new folder**.
3. Open it the same way. Your data, backups and settings stay where they are and are picked up automatically. The database upgrades itself if needed, and a backup is kept.
4. Delete the old program folder when you are happy with the new one.

If a new version misbehaves, close it and reopen the previous folder. Your data folder is shared, and older versions can read it. (Very occasionally an upgrade changes the database so that an older version cannot read it. The automatic backups in the `backups` folder cover that case, and I will say so in the release notes.)

## 7. Making your own changes

Everything is in plain text files, so you can edit them with any text editor:
- `tally_app/web/style.css`: all colours and spacing. The colours are named at the top (look for `--blue`, `--red` and so on), separately for light and dark.
- `tally_app/web/app.js`: the screens and their text.
- `tally_app/*.py`: the engine (rules, ratings, backups, TMDB).

To check you have not broken anything, run the automatic tests: `python -m unittest discover -s tests -p "test_*.py"`. They take about half a minute and should end with OK.

## 8. Not yet tested on a real machine

I tested everything I can in my own environment, but I cannot run Windows or a Mac here. So the first real runs on Windows (and the Mac builds) are exactly what this testing is for. Anything that behaves differently from what this page says is worth telling me about.
