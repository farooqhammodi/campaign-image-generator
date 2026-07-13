import os
import base64
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "history.db"))

MAX_VARIATIONS = 4  # cap per request to keep response times and provider cost reasonable

app = FastAPI(title="Campaign Image Generator")

# Same-origin deployment (frontend served from this app) means CORS is mostly a
# non-issue, but keep it open in case the frontend is hosted separately.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN")
if not CF_ACCOUNT_ID or not CF_API_TOKEN:
    raise RuntimeError(
        "CF_ACCOUNT_ID and CF_API_TOKEN environment variables must both be set. "
        "Copy .env.example to .env and fill them in — see README for how to get "
        "these from a free Cloudflare account."
    )

CF_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"
CF_URL = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}"}


# ---------- Database ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS generations (
            id TEXT PRIMARY KEY,
            prompt TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS images (
            id TEXT PRIMARY KEY,
            generation_id TEXT NOT NULL,
            image_base64 TEXT NOT NULL,
            content_type TEXT NOT NULL,
            FOREIGN KEY (generation_id) REFERENCES generations (id)
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ---------- Models ----------

class CampaignRequest(BaseModel):
    prompt: str
    num_variations: int = 1


# ---------- Cloudflare Workers AI call ----------

def call_cloudflare(prompt: str):
    """Returns (image_bytes, content_type, error_message)."""
    try:
        response = requests.post(
            CF_URL, headers=HEADERS, json={"prompt": prompt}, timeout=60
        )
    except requests.exceptions.RequestException as e:
        return None, None, f"Connection error: {str(e)}"

    content_type = response.headers.get("content-type", "")

    if response.status_code == 200 and "image" in content_type:
        return response.content, content_type, None

    # Errors (and occasionally success-with-metadata) come back as JSON
    try:
        data = response.json()
        errors = data.get("errors") or [{"message": "Unknown error"}]
        message = "; ".join(e.get("message", str(e)) for e in errors)
    except ValueError:
        message = response.text

    return None, None, f"Cloudflare error ({response.status_code}): {message}"


# ---------- API routes ----------

@app.get("/api/v1/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/v1/generate-campaign")
def generate_campaign(request: CampaignRequest):
    prompt = request.prompt.strip()
    if not prompt:
        return {"status": "error", "message": "Prompt cannot be empty"}

    num_variations = max(1, min(request.num_variations, MAX_VARIATIONS))

    images = []
    errors = []
    for _ in range(num_variations):
        content, content_type, error = call_cloudflare(prompt)
        if error:
            errors.append(error)
            continue
        images.append(
            {
                "image_base64": base64.b64encode(content).decode("utf-8"),
                "content_type": content_type,
            }
        )

    if not images:
        return {
            "status": "error",
            "message": "All variations failed to generate",
            "details": errors,
        }

    generation_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    conn.execute(
        "INSERT INTO generations (id, prompt, created_at) VALUES (?, ?, ?)",
        (generation_id, prompt, created_at),
    )
    for img in images:
        conn.execute(
            "INSERT INTO images (id, generation_id, image_base64, content_type) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), generation_id, img["image_base64"], img["content_type"]),
        )
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "generation_id": generation_id,
        "prompt": prompt,
        "created_at": created_at,
        "images": images,
        "requested": num_variations,
        "failed_count": num_variations - len(images),
    }


@app.get("/api/v1/history")
def get_history(limit: int = 30):
    conn = get_db()
    generations = conn.execute(
        "SELECT id, prompt, created_at FROM generations ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()

    history = []
    for gen in generations:
        images = conn.execute(
            "SELECT image_base64, content_type FROM images WHERE generation_id = ?",
            (gen["id"],),
        ).fetchall()
        history.append(
            {
                "id": gen["id"],
                "prompt": gen["prompt"],
                "created_at": gen["created_at"],
                "images": [
                    {"image_base64": img["image_base64"], "content_type": img["content_type"]}
                    for img in images
                ],
            }
        )
    conn.close()
    return {"status": "success", "history": history}


@app.delete("/api/v1/history/{generation_id}")
def delete_history_item(generation_id: str):
    conn = get_db()
    conn.execute("DELETE FROM images WHERE generation_id = ?", (generation_id,))
    conn.execute("DELETE FROM generations WHERE id = ?", (generation_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ---------- Static frontend ----------
# Serves the frontend and API from the same origin/port, so there's a single
# service to deploy and no CORS complications in production.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
