import argparse
from datetime import datetime, timezone
import re
import sys
from pathlib import Path
import httpx

APP_ID = "936619743392459"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def extractShortcode(raw_target: str) -> str:
    match = re.search(r"(?:/p/|/reel/|/tv/)([A-Za-z0-9_-]+)", raw_target)
    if match:
        return match.group(1)
    cleaned = raw_target.strip("/ ")
    if "/" not in cleaned and len(cleaned) < 40:
        return cleaned
    raise ValueError(f"couldn't extract shortcode from {raw_target}")


def is_username(target: str) -> bool:
    target = target.strip("@/ ")
    if target.startswith("http://") or target.startswith("https://"):
        path = target.split("instagram.com/")[-1].split("?")[0].strip("/")
        if "/" not in path and path not in ("p", "reel", "tv", "stories"):
            return True
        return False
    return bool(re.match(r"^[A-Za-z0-9._]{1,30}$", target))


def clean_username(target: str) -> str:
    target = target.strip("@/ ")
    if "instagram.com/" in target:
        target = target.split("instagram.com/")[-1].split("?")[0].strip("/")
    return target


def fetch_post_data(shortcode: str, sessionid: str | None = None) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "X-IG-App-ID": APP_ID,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/p/{shortcode}/",
    }
    cookies = {}
    if sessionid:
        cookies["sessionid"] = sessionid

    url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
    with httpx.Client(headers=headers, cookies=cookies, timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code == 404:
            raise RuntimeError(f"post {shortcode} not found or account is private")
        if resp.status_code != 200:
            raise RuntimeError(f"ig returned status {resp.status_code} for {shortcode}")
        return resp.json()


def fetch_profile_posts(username: str, sessionid: str | None = None, count: int = 12) -> list[dict]:
    # Web profile info endpoint is much less prone to challenge blocks than graphql queries
    headers = {
        "User-Agent": USER_AGENT,
        "X-IG-App-ID": APP_ID,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://www.instagram.com/{username}/",
    }
    cookies = {}
    if sessionid:
        cookies["sessionid"] = sessionid

    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    with httpx.Client(headers=headers, cookies=cookies, timeout=20.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code == 404:
            raise RuntimeError(f"user @{username} not found")
        if resp.status_code != 200:
            raise RuntimeError(f"failed to fetch profile @{username}: status {resp.status_code}")
        raw = resp.json()

    user_data = raw.get("data", {}).get("user")
    if not user_data:
        raise RuntimeError(f"empty profile payload for @{username}")
    if user_data.get("is_private") and not user_data.get("followed_by_viewer") and not sessionid:
        raise RuntimeError(f"@{username} is private; supply a valid --session cookie")

    edges = user_data.get("edge_owner_to_timeline_media", {}).get("edges", [])
    shortcodes = [e["node"]["shortcode"] for e in edges[:count] if "node" in e]
    return shortcodes


def _best_media(item_dict: dict) -> dict | None:
    mtype = item_dict.get("media_type")
    if mtype == 2:
        candidates = item_dict.get("video_versions", [])
        if not candidates:
            return None
        # picking max area ensures full uncompressed preview
        best = max(candidates, key=lambda x: x.get("width", 0) * x.get("height", 0))
        return {"url": best["url"], "is_video": True}
    elif mtype == 1:
        candidates = item_dict.get("image_versions2", {}).get("candidates", [])
        if not candidates:
            return None
        best = max(candidates, key=lambda x: x.get("width", 0) * x.get("height", 0))
        return {"url": best["url"], "is_video": False}
    return None


def extract_items(data: dict) -> tuple[str, list[dict]]:
    """Pulls shortcode timestamp and media objects from raw __a=1 payload."""
    items = data.get("items", [])
    if not items:
        return "", []
    root = items[0]
    # print("DEBUG root keys:", root.keys())
    
    ts = root.get("taken_at")
    date_prefix = ""
    if ts:
        date_prefix = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d_")

    media_type = root.get("media_type")
    out = []

    # FIXME: if ig starts splitting audio stream for reels into dash mpd, need ffmpeg merge here
    if media_type == 8:  # carousel
        carousel = root.get("carousel_media", [])
        for sub in carousel:
            res = _best_media(sub)
            if res:
                out.append(res)
    else:
        res = _best_media(root)
        if res:
            out.append(res)

    return date_prefix, out


def download_file(client: httpx.Client, url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        print(f"  skipping existing {path.name}")
        return

    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    print(f"  saved {path.name} ({path.stat().st_size // 1024} KB)")


def process_post(client: httpx.Client, shortcode: str, targetFolder: Path, sessionid: str | None = None) -> None:
    data = fetch_post_data(shortcode, sessionid)
    date_prefix, items = extract_items(data)
    if not items:
        print(f"  no media in {shortcode}")
        return

    for idx, itm in enumerate(items):
        ext = "mp4" if itm["is_video"] else "jpg"
        suffix = f"_{idx + 1}" if len(items) > 1 else ""
        fname = f"{date_prefix}{shortcode}{suffix}.{ext}"
        download_file(client, itm["url"], targetFolder / fname)


def main():
    parser = argparse.ArgumentParser(description="download full-res media from instagram without a browser")
    parser.add_argument("target", help="post url, shortcode, or profile username")
    parser.add_argument("-o", "--out", default="downloads", help="output directory")
    parser.add_argument("-s", "--session", default=None, help="sessionid cookie value for private posts")
    parser.add_argument("-n", "--count", type=int, default=12, help="number of recent posts if targeting a profile")
    args = parser.parse_args()

    base_dir = Path(args.out)
    dl_headers = {"User-Agent": USER_AGENT}

    with httpx.Client(headers=dl_headers, timeout=30.0) as dl_client:
        # check if input is a profile or a specific post
        if "/p/" not in args.target and "/reel/" not in args.target and "/tv/" not in args.target and is_username(args.target):
            uname = clean_username(args.target)
            print(f"fetching profile posts for @{uname}...")
            try:
                codes = fetch_profile_posts(uname, args.session, count=args.count)
            except Exception as e:
                print(f"error: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"found {len(codes)} recent posts")
            profile_dir = base_dir / uname
            for code in codes:
                print(f"processing {code}...")
                try:
                    process_post(dl_client, code, profile_dir, args.session)
                except Exception as err:
                    print(f"  failed on {code}: {err}")
        else:
            try:
                shortcode = extractShortcode(args.target)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                sys.exit(1)
            print(f"fetching {shortcode}...")
            process_post(dl_client, shortcode, base_dir, args.session)


if __name__ == "__main__":
    main()
