import requests
from bs4 import BeautifulSoup
import json
import time
import os
import re
from urllib.parse import urljoin, urlparse


session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0"
})

IMAGE_ROOT = "downloaded_images"


def fetch_with_retry(url, retries=5, default_wait=5):
    for attempt in range(retries):
        resp = session.get(url, timeout=10)

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", default_wait))
            print(f"429 Too Many Requests: {url} -> retrying after {wait}s")
            time.sleep(wait)
            continue

        resp.raise_for_status()
        time.sleep(1)
        return resp

    raise RuntimeError(f"request retries exhausted: {url}")


def make_safe_name(text):
    safe_text = re.sub(r"[^\w\-]+", "_", text.strip())
    return safe_text.strip("_") or "untitled"


def guess_extension(image_url, response):
    path = urlparse(image_url).path
    ext = os.path.splitext(path)[1].lower()

    if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
        return ext

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    content_type_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    return content_type_map.get(content_type, ".bin")


def download_single_image(img_url, alt_text, page_dir, image_index):
    response = fetch_with_retry(img_url)
    ext = guess_extension(img_url, response)
    filename = f"image_{image_index}{ext}"
    file_path = os.path.join(page_dir, filename)

    with open(file_path, "wb") as f:
        f.write(response.content)

    return {
        "alt": alt_text,
        "url": img_url,
        "path": file_path,
    }


def get_help_links(url):
    html = fetch_with_retry(url).text
    soup = BeautifulSoup(html, "html.parser")

    links = {}
    seen = set()

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"].strip()

        if not text:
            continue

        if "/help/articles/" not in href:
            continue

        if href.startswith("/"):
            href = "https://slack.com" + href
        elif href.startswith("https://"):
            pass
        else:
            continue

        if href in seen:
            continue
        seen.add(href)

        links[text] = href

    return links

def div_box_info(url):

    resp = fetch_with_retry(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    boxes = soup.find_all("div", class_="boxed roles")

    for box in boxes:
        title = box.select_one("strong")
        roles = [li.get_text(" ", strip=True) for li in box.select("li")]

        results.append({
            "title": title.get_text(strip=True) if title else None,
            "roles": roles
        })
    print(results)
    return results
            
def get_link_info(url, page_name):
    resp = fetch_with_retry(url)

    soup = BeautifulSoup(resp.text, "html.parser")

    content = soup.select_one("div.article_body") or soup.select_one("main")

    if content is None:
        return []

    sections = []
    current_section = None
    seen_images = set()
    image_index = 1
    page_dir = os.path.join(IMAGE_ROOT, make_safe_name(page_name))
    os.makedirs(page_dir, exist_ok=True)

    for tag in content.find_all(["h1", "h2", "h3", "p", "ul", "ol", "img"]):

        if tag.name in ["h1", "h2", "h3"]:
            if current_section:
                sections.append(current_section)

            current_section = {
                "title": tag.get_text(strip=True),
                "content": [],
                "images": []
            }

        elif tag.name == "img":
            if current_section is None:
                continue

            src = tag.get("src", "").strip()
            if not src:
                continue

            image_url = urljoin(url, src)
            if image_url in seen_images:
                continue
            seen_images.add(image_url)

            try:
                image_info = download_single_image(
                    image_url,
                    tag.get("alt", "").strip(),
                    page_dir,
                    image_index
                )
                current_section["images"].append(image_info)
                image_index += 1
            except Exception as e:
                print(f"failed to save image: {image_url} -> {e}")

        else:
            if current_section:
                current_section["content"].append(
                    tag.get_text(" ", strip=True)
                )

    if current_section:
        sections.append(current_section)

    return sections

if __name__ == "__main__":
    urls_eng = [
        "https://slack.com/help/categories/360000049043",
        "https://slack.com/help/categories/200111606",
        "https://slack.com/help/categories/360000047906",
        "https://slack.com/help/categories/360000047926",
        "https://slack.com/help/categories/200122103",
    ]

    urls_kor = [
        "https://slack.com/intl/ko-kr/help/categories/360000049043",
        "https://slack.com/intl/ko-kr/help/categories/200111606",
        "https://slack.com/intl/ko-kr/help/categories/360000047906",
        "https://slack.com/intl/ko-kr/help/categories/360000047926",
        "https://slack.com/intl/ko-kr/help/categories/200122103" 
    ]

    test = ["https://slack.com/intl/ko-kr/help/categories/360000047926"]

    links_dict = {}
    info_list = []
    
    for url in urls_eng:
        link_dict = get_help_links(url)
        links_dict.update(link_dict)

    for text, href in links_dict.items():
        print(text, ":", href)
        box_role = div_box_info(href)

        sections = get_link_info(href, text)

        # for section in sections:
        #     print(section)

        data = {
            "page" : text,
            "url" : href,
            "box_role" : box_role,
            "section" : sections
        }

        info_list.append(data)

        with open("Slack_eng_free.json", "w", encoding="utf-8") as f:
            json.dump(info_list, f, ensure_ascii=False, indent=4)
