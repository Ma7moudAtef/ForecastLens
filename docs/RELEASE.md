# Producing and downloading a Windows build

Every build is made by GitHub, on a clean Windows machine, from the code on
`main`. You never need Python, a build tool, or a Windows machine of your own.

---

## 1. Get the latest build (no clicking required)

A build starts automatically every time a change lands on `main`. To fetch it:

1. Open the repository on **github.com**.
2. Click the **Actions** tab (top of the page, next to *Pull requests*).
3. In the left sidebar click **Build Windows EXE**.
4. Click the newest run at the top of the list — a green ✓ means it passed.
5. Scroll to the bottom, to the **Artifacts** box.
6. Click **ForecastLens-windows-`<sha>`** to download the zip.

The `<sha>` is the first characters of the commit the build came from, so two
downloads with different names are genuinely different builds. The same
string appears in the app's sidebar, which is how you match a user's report
to a build.

Artifacts stay for 90 days, and only the **10 most recent** are kept.

## 2. Build on demand (the manual button)

1. **Actions → Build Windows EXE**.
2. Click **Run workflow** (right-hand side).
3. Choose the branch, leave *Run the exe/source parity suite* ticked, and
   click the green **Run workflow** button.
4. Wait for the ✓, then download from **Artifacts** as above.

## 3. Publish a versioned release

Tagging is what turns a build into a downloadable Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow builds, verifies, creates a **Release** named after the tag and
attaches `ForecastLens-windows-<sha>.zip` to it. Releases live under the
repository's **Releases** section and never expire.

## 4. Install and run

1. Download the zip.
2. Right-click it → **Properties** → tick **Unblock** if that box is present
   → **OK**. (Windows marks files that came from the internet; unblocking
   here avoids warnings later.)
3. Right-click → **Extract All…** and extract the whole folder. Do not run
   the exe from inside the zip viewer — the app needs the files beside it.
4. Open the extracted folder and double-click **ForecastLens-Start.bat**.
5. A console window opens and reports its startup checks, then your browser
   opens at `http://localhost:8501`.

Keep the console window open while you use the app; closing it stops the
engine. No installation, no administrator rights, and nothing is written to
the registry. Your data lives in `%LOCALAPPDATA%\ForecastLens`.

---

## What the build checks before it will publish

A build fails — and produces no downloadable zip — unless all of these pass:

| Check | What it proves |
|---|---|
| Startup self-check | The packaged app can find its files, write its data folder and open its database |
| Server probe | The Streamlit interface actually serves pages |
| **Parity suite** | The exe produces **the same numbers** as the source version: identical forecasts, identical model choices, identical series classification |
| Bundle size | Under the 300 MB budget |

The parity suite is the important one. A build that runs but forecasts
differently is worse than one that crashes, because nobody notices. If it
fails, the workflow stops with `PARITY FAILED` and nothing is published.

---

## Troubleshooting

### "Windows protected your PC" (SmartScreen)

Expected. The build is not code-signed, and SmartScreen warns about any
executable it has not seen many times before. It is a reputation warning,
not a virus detection.

To proceed: click **More info** → **Run anyway**.

To avoid it entirely, unblock the zip *before* extracting (step 2 above) — the
warning usually comes from the "downloaded from the internet" mark being
inherited by every extracted file.

If your organisation blocks SmartScreen overrides, ask IT to allow the folder,
or to add a code-signing certificate to the build. Signing is a one-line
change to the workflow once a certificate exists.

### Antivirus deletes or quarantines the exe

PyInstaller bundles are frequently flagged by heuristics, because packing an
interpreter plus code into one executable resembles what some malware does.
Nothing is actually wrong with the file.

What to do, in order of preference:

1. Ask IT to allow the extracted folder (an exclusion by path).
2. Extract to a folder your antivirus does not scan aggressively — a folder
   under your own user profile rather than `Downloads`.
3. Re-extract the zip in full. A partially quarantined folder shows up as
   **Bundled files: FAIL** in the startup check, naming the missing file.

The app never installs a service, never writes to the registry, and never
requires administrator rights. If a tool reports otherwise, it is a false
positive on the packer.

### The console window opens and closes immediately

Run `ForecastLens.exe` directly from a Command Prompt so the message stays
visible:

```
cd path\to\ForecastLens
ForecastLens.exe --selfcheck
```

The self-check names exactly which of the four things is wrong — data
folder, database, bundled files or dependencies — and what to do about it.

### "cannot write to …" in the startup check

The app writes to `%LOCALAPPDATA%\ForecastLens`. On a locked-down machine
that may be denied. Point it somewhere you can write:

```
set FORECASTLENS_DATA_DIR=D:\forecastlens-data
ForecastLens.exe
```

### The browser does not open

Open `http://localhost:8501` yourself. If nothing answers, another program may
be using port 8501 — close it and relaunch.

### Which build is this?

The sidebar footer shows `build <sha>` and the build timestamp, and
`ForecastLens.exe --version` prints the same string. Quote it in any bug
report: it identifies the exact code that produced the results.
