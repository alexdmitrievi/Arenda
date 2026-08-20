"""Fetch a public Telegram channel's posts via the t.me/s/ web preview.

Bypasses both the MTProto block and the login requirement: the server-side
preview renders message text and media links. Needs TG_PROXY (socks5) on
blocked networks.

Usage:
  python channel_web.py fetch <channel> <count> <outdir>
"""

import html
import json
import os
import re
import sys
import time
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_WRAP_RE = re.compile(r'data-post="([^"]+)"', re.S)
_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S
)
_DATE_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_PHOTO_RE = re.compile(r"background-image:url\('([^']+)'\)")
_LINK_PREVIEW_RE = re.compile(
    r'<a class="tgme_widget_message_link_preview[^"]*" href="([^"]+)"', re.S
)
_TAGS_RE = re.compile(r"<[^>]+>")


def _proxy_handler() -> urllib.request.ProxyHandler | None:
    raw = os.environ.get("TG_PROXY", "")
    if not raw:
        return None
    scheme, host, port = raw.replace("/", "").split(":")
    return urllib.request.ProxyHandler({"http": f"{scheme}://{host}:{port}",
                                        "https": f"{scheme}://{host}:{port}"})


def _opener() -> urllib.request.OpenerDirector:
    handlers = []
    proxy = _proxy_handler()
    if proxy:
        handlers.append(proxy)
    return urllib.request.build_opener(*handlers)


def fetch_page(opener, channel: str, before: str | None = None) -> tuple[str, list[dict], str | None]:
    url = f"https://t.me/s/{channel}"
    if before:
        url += f"?before={before}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=30) as resp:
        page = resp.read().decode("utf-8", "replace")

    posts = []
    next_before = None
    markers = list(_WRAP_RE.finditer(page))
    for i, match in enumerate(markers):
        data_post = match.group(1)
        msg_id = data_post.split("/", 1)[1]
        end = markers[i + 1].start() if i + 1 < len(markers) else len(page)
        block = page[match.start():end]
        text = ""
        tm = _TEXT_RE.search(block)
        if tm:
            text = html.unescape(_TAGS_RE.sub("", tm.group(1))).strip()
        date = ""
        dm = _DATE_RE.search(block)
        if dm:
            date = dm.group(1)
        photos = _PHOTO_RE.findall(block)
        previews = _LINK_PREVIEW_RE.findall(block)
        posts.append({
            "id": int(msg_id),
            "date": date,
            "text": text,
            "images": photos,
            "previews": previews,
        })
        if next_before is None:
            next_before = msg_id
    return page, posts, next_before


def download_image(opener, url: str, dest: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=60) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"IMG_FAIL {url}: {e}")
        return False


def main() -> None:
    channel = sys.argv[2]
    count = int(sys.argv[3])
    outdir = sys.argv[4]
    os.makedirs(outdir, exist_ok=True)
    opener = _opener()

    posts: list[dict] = []
    before = None
    while len(posts) < count:
        _, page_posts, before = fetch_page(opener, channel, before)
        if not page_posts:
            break
        posts.extend(page_posts)
        print(f"page: +{len(page_posts)} total={len(posts)} before={before}")
        if before is None:
            break
        time.sleep(1.5)

    posts = posts[:count]
    images = 0
    for post in posts:
        saved = []
        for url in post["images"]:
            fname = f"msg_{post['id']}_{len(saved)}.jpg"
            if not download_image(opener, url, os.path.join(outdir, fname)):
                continue
            saved.append(fname)
            images += 1
            time.sleep(0.4)
        post["local_images"] = saved

    with open(os.path.join(outdir, "messages.json"), "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)
    print(f"DONE posts={len(posts)} images={images}")


if __name__ == "__main__":
    main()
