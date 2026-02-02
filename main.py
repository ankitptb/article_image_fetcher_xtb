import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from io import BytesIO
from PIL import Image
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

# ---------------- CONFIG ----------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

MIN_WIDTH = 600
MIN_HEIGHT = 300
MIN_RATIO = 0.8
MAX_RATIO = 2.2
MAX_IMAGES_PER_ARTICLE = 1  # 🔥 important

# -------------- FASTAPI -----------------

app = FastAPI()

class ArticleRequest(BaseModel):
    articleUrls: List[str]

# -------- HEALTH CHECK --------

@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "Article Image Fetcher",
    }

# -------- CLOUDINARY INIT --------

def init_cloudinary():
    try:
        cloudinary.config(
            cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
            api_key=os.environ["CLOUDINARY_API_KEY"],
            api_secret=os.environ["CLOUDINARY_API_SECRET"],
        )
    except KeyError:
        raise HTTPException(status_code=500, detail="Cloudinary env vars missing")

# -------- IMAGE EXTRACTION --------

def extract_image_urls(article_url):
    response = requests.get(article_url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "lxml")

    image_urls = []

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        image_urls.append(urljoin(article_url, og["content"]))

    for fig in soup.find_all("figure"):
        img = fig.find("img")
        if img and img.get("src"):
            image_urls.append(urljoin(article_url, img["src"]))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            image_urls.append(urljoin(article_url, src))

    return list(dict.fromkeys(image_urls))

# -------- IMAGE VALIDATION --------

def fetch_and_validate_image(image_url):
    if image_url.startswith("data:image") or image_url.lower().endswith(".svg"):
        return None

    try:
        r = requests.get(image_url, headers=HEADERS, timeout=15)
        img = Image.open(BytesIO(r.content)).convert("RGB")

        w, h = img.size
        ratio = w / h

        if (
            w >= MIN_WIDTH
            and h >= MIN_HEIGHT
            and MIN_RATIO <= ratio <= MAX_RATIO
        ):
            return img

    except Exception:
        return None

    return None

# -------- CLOUDINARY UPLOAD --------

def upload_to_cloudinary(img, public_id):
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    buffer.seek(0)

    result = cloudinary.uploader.upload(
        buffer,
        folder="article-images",
        public_id=public_id,
        overwrite=True,
        resource_type="image",
    )

    return result["secure_url"]

# -------- MAIN API --------

@app.post("/fetch-article-images")
def fetch_article_images(payload: ArticleRequest):
    init_cloudinary()

    results = []

    for idx, article_url in enumerate(payload.articleUrls):
        images = []

        image_urls = extract_image_urls(article_url)

        for img_idx, image_url in enumerate(image_urls):
            img = fetch_and_validate_image(image_url)
            if not img:
                continue

            public_id = f"article_{idx+1}_hero"
            cloud_url = upload_to_cloudinary(img, public_id)
            images.append(cloud_url)
            break  # ✅ only best image

        results.append({
            "articleUrl": article_url,
            "articleImages": images
        })

    return {
        "count": len(results),
        "articles": results
    }
