import os
import requests
import boto3
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from io import BytesIO
from PIL import Image
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
MAX_IMAGES_PER_ARTICLE = 1

MAX_FILE_SIZE_KB = 800
S3_FOLDER_ARTICLE = "xtbscrapimg"

# ---------------- FASTAPI ----------------

app = FastAPI()

class ArticleRequest(BaseModel):
    articleUrls: List[str]

@app.get("/")
def health():
    return {"status": "ok"}

# ---------------- S3 CLIENT ----------------

def get_s3_client():
    try:
        return boto3.client(
            "s3",
            region_name=os.environ["AWS_REGION"],
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        )
    except KeyError:
        raise HTTPException(status_code=500, detail="AWS env vars missing")

BUCKET_NAME = os.environ.get("AWS_S3_BUCKET")

# ---------------- IMAGE SCRAPING ----------------

def extract_image_urls(article_url):
    response = requests.get(article_url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "lxml")

    urls = []

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        urls.append(urljoin(article_url, og["content"]))

    for fig in soup.find_all("figure"):
        img = fig.find("img")
        if img and img.get("src"):
            urls.append(urljoin(article_url, img["src"]))

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            urls.append(urljoin(article_url, src))

    return list(dict.fromkeys(urls))

# ---------------- IMAGE VALIDATION ----------------

def fetch_and_validate_image(image_url):
    if image_url.startswith("data:image") or image_url.lower().endswith(".svg"):
        return None

    try:
        r = requests.get(image_url, headers=HEADERS, timeout=15)
        img = Image.open(BytesIO(r.content)).convert("RGB")

        w, h = img.size
        ratio = w / h

        if w >= MIN_WIDTH and h >= MIN_HEIGHT and MIN_RATIO <= ratio <= MAX_RATIO:
            return img
    except Exception:
        return None

    return None

# ---------------- IMAGE COMPRESS ----------------

def compress_image(img):
    quality = 85
    buffer = BytesIO()

    while quality >= 60:
        buffer.seek(0)
        buffer.truncate(0)

        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        size_kb = buffer.tell() / 1024

        if size_kb <= MAX_FILE_SIZE_KB:
            buffer.seek(0)
            return buffer

        quality -= 5

    buffer.seek(0)
    return buffer

# ---------------- S3 UPLOAD ----------------

def upload_to_s3(s3, buffer, key):
    s3.upload_fileobj(
        buffer,
        BUCKET_NAME,
        key,
        ExtraArgs={
            "ContentType": "image/jpeg",
        },
    )

    return f"https://xtb-internal-tools.s3.us-east-1.amazonaws.com/{key}"

# ---------------- MAIN API ----------------

@app.post("/fetch-article-images")
def fetch_article_images(payload: ArticleRequest):
    s3 = get_s3_client()

    results = []

    for idx, article_url in enumerate(payload.articleUrls):
        article_images = []

        image_urls = extract_image_urls(article_url)

        for image_url in image_urls:
            img = fetch_and_validate_image(image_url)
            if not img:
                continue

            buffer = compress_image(img)

            key = f"{S3_FOLDER_ARTICLE}/article_{idx+1}_hero.jpg"
            image_url_s3 = upload_to_s3(s3, buffer, key)

            article_images.append(image_url_s3)
            break

        results.append({
            "articleUrl": article_url,
            "articleImages": article_images
        })

    return {
        "count": len(results),
        "articles": results
    }
