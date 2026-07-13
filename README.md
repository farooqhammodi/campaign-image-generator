# 🎨 Proof — Campaign Image Generator

![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688)
![Tests](https://github.com/YOUR_USERNAME/YOUR_REPO_NAME/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

A self-hosted tool for generating marketing/campaign images from a text prompt,
built on FastAPI and Cloudflare Workers AI (Stable Diffusion XL). Pick a campaign
format (social post, banner ad, poster, product shot) and get correctly-sized,
style-tuned variations — not just a raw prompt passthrough. Every generation is
saved to a persistent contact-sheet history. Backend and frontend ship as one
deployable service.

Built to run entirely on free-tier infrastructure: Cloudflare Workers AI gives
10,000 neurons/day at no cost, no credit card required.

**Live demo:** _add your deployed URL here once you've deployed it (see Deploy section below)_

> Replace `YOUR_USERNAME/YOUR_REPO_NAME` in the Tests badge URL above with your
> actual GitHub path once pushed, so the badge resolves.

---

Generate campaign images from a text prompt using Cloudflare Workers AI (Stable Diffusion XL),
with prompt history and multiple image variations per request. Single FastAPI service
serves both the API and the frontend, so there's one thing to run and one thing to deploy.

Runs on Cloudflare's free tier: 10,000 neurons/day, no credit card required.

## Features
- Text-to-image generation via Cloudflare Workers AI (free daily quota)
- **Campaign format presets** — Social Media Post, Banner Ad, Poster, Product Shot —
  each maps to real generation parameters (aspect ratio + a tuned style suffix),
  enforced server-side so the frontend can't override them
- 1–4 variations per prompt in a single request
- Persistent prompt/image history (SQLite) with a contact-sheet UI, viewable and
  deletable from the sidebar
- One deployable service (backend serves the frontend as static files — no CORS
  setup needed)
- Automated test suite (pytest) covering the API's core logic and error paths,
  run in CI on every push via GitHub Actions

## Project structure
```
campaign-app/
├── main.py                        # FastAPI app: API routes + serves static/ as the frontend
├── static/
│   └── index.html                 # Frontend (vanilla HTML/CSS/JS, no build step)
├── tests/
│   └── test_main.py               # pytest suite (mocks the Cloudflare call — runs offline)
├── .github/workflows/tests.yml    # CI: runs pytest on every push/PR to main
├── requirements.txt
├── requirements-dev.txt           # pytest + httpx, for running tests locally
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── .dockerignore
```

---

## 1. Get free Cloudflare Workers AI credentials

1. Sign up at https://dash.cloudflare.com/sign-up (no credit card needed for the free tier)
2. Your **Account ID** is on the right-hand sidebar of the main Cloudflare dashboard —
   copy it
3. Go to **My Profile → API Tokens** (https://dash.cloudflare.com/profile/api-tokens)
4. Click **Create Token → Custom Token**
5. Under permissions, add: **Account → Workers AI → Read** (or "Edit", either works
   for running inference)
6. Create the token and copy it — you won't see it again

You now have two values: `CF_ACCOUNT_ID` and `CF_API_TOKEN`.

**Free tier limits:** 10,000 neurons/day, no credit card required. An SDXL image costs
roughly a few hundred neurons, so this comfortably covers dozens of images a day for
personal use. If you exceed it, requests just fail until the daily quota resets — there's
no surprise billing on the free Workers plan.

---

## 2. Run locally (no Docker)

```bash
cd campaign-app
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste your CF_ACCOUNT_ID and CF_API_TOKEN
```

Run it:
```bash
python main.py
```

Open **http://localhost:8000** in your browser — that's the frontend and API together.

---

## 3. Run locally with Docker

```bash
cp .env.example .env
# edit .env and paste your CF_ACCOUNT_ID and CF_API_TOKEN

docker compose up --build
```

Open **http://localhost:8000**. The SQLite history file persists in a Docker volume
(`history-data`) across container restarts.

---

## 4. Run the test suite

Tests mock the Cloudflare API call, so they run fully offline and cost nothing:

```bash
pip install -r requirements-dev.txt
pytest -v
```

These same tests run automatically in GitHub Actions on every push to `main`
(see `.github/workflows/tests.yml`) — that's what the Tests badge at the top
of this README reflects once the repo is on GitHub.

---

## 5. Push this to your own GitHub repo

From inside the `campaign-app` folder:

```bash
git init
git add .
git commit -m "Initial commit: campaign image generator"
```

Create an empty repo on GitHub (no README/gitignore, so it doesn't conflict), then:

```bash
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

Your `.env` file is excluded by `.gitignore`, so your token won't be committed.
Double-check with `git status` before your first push that `.env` isn't listed.

### Updating the repo after the first push

Once the repo exists on GitHub, any time you change files locally:

```bash
git status              # see what changed
git add .
git commit -m "Describe what you changed"
git push
```

That's the full cycle — `add` stages changes, `commit` saves them locally with a
message, `push` sends them to GitHub. No need to `git init` or `remote add` again;
that's only for the very first setup.

---

## 6. Deploy (Railway — simplest option)

Railway auto-detects the `Dockerfile` and needs no extra config.

1. Go to https://railway.app and sign in with GitHub
2. **New Project → Deploy from GitHub repo** → select your repo
3. Once it's created, go to the service's **Variables** tab and add:
   - `CF_ACCOUNT_ID` = your Cloudflare account ID
   - `CF_API_TOKEN` = your Cloudflare API token
4. Railway builds the Dockerfile and gives you a public URL automatically
5. **Persisting history across deploys (optional):** by default the container's
   filesystem resets on redeploy, so history would reset too. If you want it to
   persist, go to the service's **Settings → Volumes**, mount a volume at
   `/app/data`, and set an environment variable `DB_PATH=/app/data/history.db`.

## Alternative: Render

1. Go to https://render.com → **New → Web Service** → connect your GitHub repo
2. Render detects the `Dockerfile` automatically
3. Under **Environment**, add `CF_ACCOUNT_ID` and `CF_API_TOKEN` with your values
4. For persistent history, add a **Disk** mounted at `/app/data` in the service
   settings, and set `DB_PATH=/app/data/history.db` as an environment variable
5. Deploy — Render gives you a public `.onrender.com` URL

Note: Render's free tier spins the service down after inactivity, so the first
request after idling will be slow (cold start on Render's side; Cloudflare itself
has no cold starts).

---

## API reference

| Method | Path                                  | Description                          |
|--------|---------------------------------------|---------------------------------------|
| GET    | `/api/v1/health`                      | Health check                          |
| GET    | `/api/v1/campaign-types`              | List available format presets and their dimensions |
| POST   | `/api/v1/generate-campaign`           | Body: `{"prompt": str, "num_variations": int, "campaign_type": str \| null}` |
| GET    | `/api/v1/history?limit=30`            | Recent generations with images        |
| DELETE | `/api/v1/history/{generation_id}`     | Delete one history entry              |

`campaign_type` is one of `social`, `banner`, `poster`, `product`, or `null` for a
default square image with no style suffix added. See `CAMPAIGN_PRESETS` in
`main.py` for exact dimensions and prompt suffixes — these are enforced
server-side regardless of what the frontend sends.

## Notes
- Images are stored as base64 directly in SQLite for simplicity. Fine for personal
  use; if this grows heavily, switch to storing images in object storage (e.g. S3
  or Cloudflare R2) and keeping only URLs in the database.
- `num_variations` is capped at 4 server-side regardless of what's sent, to control
  how fast you burn through the daily free neuron quota.
- Cloudflare's free tier (10,000 neurons/day) resets daily, not monthly — much more
  forgiving for regular use than Hugging Face's small monthly free credit.
- If you want higher-quality output later, Cloudflare also hosts a FLUX model
  (`@cf/black-forest-labs/flux-1-schnell`) — swap `CF_MODEL` in `main.py` to try it,
  though check current free-tier neuron cost for that model before relying on it.
- Database schema migrations (e.g. the `campaign_type` and `original_prompt`
  columns) are applied automatically on startup via a simple `ALTER TABLE IF NOT
  EXISTS`-style check in `init_db()`, so upgrading an existing install won't lose
  history data.

## Adding a screenshot to this README

Once you have the app running with a few generations in the contact sheet, add a
screenshot so people don't have to run it to see what it does:

1. Take a screenshot of the app (prompt + a generated result looks best)
2. Save it in the repo, e.g. `docs/screenshot.png`
3. Add this near the top of the README, right after the description:
   ```markdown
   ![Screenshot](docs/screenshot.png)
   ```
4. Commit and push as usual (`git add .`, `git commit -m "Add screenshot"`, `git push`)
