# Building the apps in the cloud (no Mac needed)

GitHub can build The Counting for Windows and for both kinds of Mac on its own computers, then **start each finished app and run its self-check**. You find out whether a Mac build works without owning a Mac.

## One-time setup (about ten minutes)

1. **Make a free GitHub account** at github.com, if you do not have one.
2. **Create a new repository** (the plus sign at the top right, then New repository). Name it anything, for example `the-counting`. *Public* repositories run builds free. *Private* works too, but I believe Mac builds then use up your free minutes much faster, so check GitHub's billing page first.
3. **Upload the project.** Unzip `TheCounting-app.zip` on your computer. On the repository page choose **Add file, then Upload files**, and drag in **everything inside the `tally` folder**, including the hidden folder named `.github`. If you cannot see it, in Windows File Explorer choose View, Show, Hidden items. Then press **Commit changes**.
4. **Check the upload.** On the repository page you should be able to open `.github`, then `workflows`, then `build.yml`. If that file is missing, the build cannot run.

## Each time you want new apps

1. Open the repository's **Actions** tab. If GitHub asks, enable workflows.
2. Choose **Build The Counting** on the left, then **Run workflow**, then the green button.
3. Wait. The tests run first on Windows, two kinds of Mac and Linux, then the builds, which can take around ten to twenty minutes in all.
4. When it finishes you see ticks or crosses. Click the run to see its jobs.

## Reading the result

- **Open each build job** (Windows, Mac Apple Silicon, Mac Intel, Linux) and its **Self-check** step. A good result starts with `ALL REQUIRED CHECKS PASSED`, then a list of PASS lines. The checks cover the app's files, database, local server, secure-connection certificates and window component, plus a secure connection to TMDB (a warning there only means the build computer could not reach TMDB).
- **For a Mac build,** also open the **Mac details** step. It shows how the app is signed and the minimum macOS version it needs.
- **Downloads** are at the bottom of the run page, under **Artifacts**: `TheCounting-windows`, `TheCounting-mac-apple-silicon`, `TheCounting-mac-intel`. The `selfcheck-...` artifacts hold each report as a file.
- **If a job has a red cross,** open it, find the first step with a red mark, and copy that step's log to me.

## Getting a link to share

Make a **release** instead of a one-off run: on the repository page, Releases, Draft a new release, type a tag such as `v0.7.1`, publish. The same build runs and the zips and a `SHA256SUMS.txt` file are attached to the release page, which has a link you can send.

## Having a Mac friend try it

1. Ask which chip they have: Apple menu, About This Mac. A chip named M-something means Apple Silicon. Intel means Intel.
2. Send them the matching zip and the Mac section of `GETTING_STARTED.md`. The first launch needs one extra step because the app is not signed with a paid Apple certificate.
3. Ask them to open The Counting, go to **Settings, then Help, then Run a self-check**, press **Copy**, and send you the text.

## What the cloud build cannot tell you

It proves the app starts, finds its files and database, and makes secure connections. It cannot show you the window, the look on a Retina screen, or the real Gatekeeper warning. Those need a person with a Mac. The self-check report from them is the next-best thing to being there.
