# Sports Betting Model — Tennis Pilot

Pulls live tennis matches, gets the API's own win prediction and odds for each,
flags value bets / high-confidence picks / arbitrage opportunities, and pushes
a notification to your phone. Once validated, the same pattern extends to
other sports.

## 1. Install dependencies

```bash
pip install requests --break-system-packages
```

## 2. Get your two free keys

- **Tennis API** (predictions, odds, arbitrage): subscribe (free tier available) at
  https://rapidapi.com/jjrm365-kIFr3Nx_odV/api/tennis-api-atp-wta-itf — this gives you
  `RAPIDAPI_KEY`. Full docs: https://tennisapidoc.matchstat.com/
- **ntfy.sh** (push notifications): no signup needed.
  1. Install the ntfy app (iOS App Store / Google Play).
  2. Pick a topic name only you would guess (e.g. `mike-tennis-bets-8x2k`) — ntfy topics
     are public by default, so anyone who knows your topic name can see your notifications.
  3. Subscribe to that topic in the app. This is `NTFY_TOPIC`.

Set both as environment variables (or edit `config.py` directly):
```bash
export RAPIDAPI_KEY="your_key_here"
export NTFY_TOPIC="your-unique-topic-name"
```

## 3. Test a single pass

```bash
python main.py --once
```
This pulls all currently live tennis matches, gets a prediction + odds for each,
logs every one to `data/predictions_log.csv`, and pushes a notification for any
value bet, high-confidence pick, or arbitrage opportunity.

No live matches at the moment it runs? It'll just log nothing and exit — try
again during an ATP/WTA event.

## 4. Run continuously

```bash
python main.py
```
Loops forever, polling every `POLL_INTERVAL_SECONDS` (default 5 min). This
needs to be hosted somewhere that stays running — see section 5 below for the
free way to do that.

## 5. Deploy on GitHub Actions (runs it 24/7 for free, no server)

This repo includes `.github/workflows/run_model.yml`, which runs `main.py --once`
on a schedule (every 15 min) using GitHub's free runners.

**Steps:**

1. Create a new **private** GitHub repo.
2. Push this whole folder to it:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
3. In the repo on GitHub: **Settings -> Secrets and variables -> Actions -> New repository secret**.
   Add two secrets:
   - `RAPIDAPI_KEY` — your Tennis API key
   - `NTFY_TOPIC` — your ntfy topic name
4. Go to the **Actions** tab — "Run tennis betting model" will run automatically every
   15 minutes. Click **"Run workflow"** to trigger a test run immediately.
5. Every run appends to `data/predictions_log.csv` and commits it back to the repo, so
   your prediction history builds up over time, viewable right in GitHub.

**Note on GitHub free tier:** private repos get 2,000 free Action minutes/month, which a
15-min-interval job comfortably fits within.

## What's next (once tennis is validated)

- Add other sports — this API is tennis-only, so other sports need their own data source
  (odds APIs, sport-specific stats APIs) plugged into the same edge-detection pattern
- Tune `EDGE_THRESHOLD` and `CONFIDENCE_THRESHOLD` in `config.py` once you see how the
  model's predictions track against real results
- Build a simple dashboard reading `data/predictions_log.csv` to track accuracy and ROI
- Consider pulling the live odds/live-score endpoints too (not just pre-match) for true
  in-match momentum betting

## Files

| File | Purpose |
|---|---|
| `config.py` | API keys, thresholds |
| `tennis_api_client.py` | Wrapper for the Tennis API (predictions, odds, arbitrage) |
| `notifier.py` | Sends push notifications via ntfy.sh |
| `main.py` | Orchestrates the full pipeline |
| `.github/workflows/run_model.yml` | Runs the pipeline on a schedule for free |
