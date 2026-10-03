# Global Mood Map — index computer (GitHub Actions)

This folder is a ready-to-upload GitHub repo. It runs `fetch_news_data.py`
automatically a few times a day (every 6 hours by default) **on GitHub's
own servers** — not your home network — which sidesteps whatever has been
blocking GDELT/GDACS requests from your connection this whole time.

This version computes the **entire composite score** server-side —
baseline, weather, news tone, and disasters all included — not just the
raw news/disaster data. The page reads one small JSON file and renders
instantly, with no live API calls needed at page-load time. That's what
makes it fast and snappy.

## Setup (about 5 minutes, all free)

1. **Create a new GitHub repository.**
   Go to https://github.com/new — name it anything (e.g. `mood-map-data`).
   Public or private both work. Don't add a README/gitignore during
   creation (keeps it empty so the upload below is clean).

2. **Upload these files to the repo**, preserving the folder structure:
   ```
   .github/workflows/fetch-data.yml
   fetch_news_data.py
   ```
   Easiest way: on the repo's GitHub page, click "Add file" → "Upload
   files", drag both — GitHub will recreate the `.github/workflows/`
   folder automatically from the file paths.

3. **Enable Actions** (usually on by default for a new repo).
   Go to the repo's **Actions** tab — you should see "Fetch Global Mood
   Map Data" listed as a workflow.

4. **Run it once manually to test:**
   Actions tab → "Compute Global Mood Map Index" → "Run workflow" button →
   Run workflow. Wait a few minutes (155 countries — weather, news, and
   disaster data all fetched and the full score computed, with a polite
   delay on the GDELT calls), then refresh the repo's file list — you
   should see a new `mood-index-data.json` file appear, committed by
   `github-actions[bot]`.

5. **Find your raw file URL.**
   Click `mood-index-data.json` in the repo → click "Raw" — copy that
   URL. It looks like:
   ```
   https://raw.githubusercontent.com/<your-username>/<repo-name>/main/mood-index-data.json
   ```

6. **Send me that URL** and I'll wire it into `global-mood-map.html` as
   the primary data source (it already has a slot for this — the page
   currently checks a local file first; I'll add this raw GitHub URL as
   the next thing it tries, before falling back to live browser fetching).

## After setup

From then on, it just runs itself — a few times a day, GitHub's servers
recompute the full index and commit it. Your page reads that file
directly and renders instantly from it, no live fetching at load time.
No cron job, no server maintenance, nothing running on your home network
at all for this part.

You can check it's alive any time via the repo's **Actions** tab (green
checkmarks = successful runs) or by watching the "Update mood index data"
commits pile up in the repo's history.

Want a different schedule? Edit the `cron:` line in
`.github/workflows/fetch-data.yml` — e.g. `"0 8,14,20 * * *"` for three
specific times a day, or `"0 */4 * * *"` for every 4 hours.
