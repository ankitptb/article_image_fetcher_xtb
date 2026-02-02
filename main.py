import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from io import BytesIO
from PIL import Image
import cloudinary
import cloudinary.uploader
from fastapi import FastAPI
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

# ------------ CLOUDINARY ----------------

cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
)

# -------------- FASTAPI -----------------

app = FastAPI()

class ArticleRequest(BaseModel):
    articleUrls: List[str]

# -------- STEP 1: Extract image URLs --------

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

# -------- STEP 2: Validate image --------

def fetch_and_validate_image(image_url):
    if image_url.startswith("data:image"):
        return None

    if image_url.lower().endswith(".svg"):
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

# -------- STEP 3: Upload to Cloudinary --------

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

# -------- MAIN API ENDPOINT --------

@app.post("/fetch-article-images")
def fetch_article_images(payload: ArticleRequest):

    response = []

    for idx, article_url in enumerate(payload.articleUrls):
        article_images = []

        image_urls = extract_image_urls(article_url)

        for img_idx, image_url in enumerate(image_urls):
            img = fetch_and_validate_image(image_url)
            if not img:
                continue

            public_id = f"article_{idx+1}_img_{img_idx+1}"
            cloud_url = upload_to_cloudinary(img, public_id)
            article_images.append(cloud_url)

        response.append({
            "json": {
                "articleImages": article_images
            }
        })

    return response
