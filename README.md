# instagram-downloader

Small CLI script I wrote to pull photos, carousels, and reels off Instagram without dealing with ad-loaded download sites that recompress media into mush.

It queries Instagram's web API and GraphQL endpoints directly, extracts direct CDN media links, and writes the files plus raw metadata JSON to disk. It handles multi-item carousels, single photo posts, and video reels.

## Install

Needs Python 3.10+.

pip install -r requirements.txt

## Usage

Grab a single post, reel, or carousel:

python igdl.py https://www.instagram.com/p/C4xxxxxxx/

Grab the latest posts from a public profile:

python igdl.py --user natgeo --limit 25

Save to a custom folder:

python igdl.py -o D:\Media\Instagram https://www.instagram.com/reel/C2yyyyyyy/

Everything downloads into structured folders named after the shortcode or username, with original upload timestamps preserved when available.

## Authentication

Instagram rate-limits or blocks unauthenticated requests pretty aggressively after a few hits. To fetch without getting choked or to download accounts you follow, pass your session cookie:

python igdl.py --session-id "YOUR_SESSIONID_COOKIE" https://www.instagram.com/p/C4xxxxxxx/

You can also set it in your shell so you don't have to keep passing the flag:

$env:IG_SESSION_ID="YOUR_SESSIONID_COOKIE"

<!-- last-sync: 2026-09-10 -->
