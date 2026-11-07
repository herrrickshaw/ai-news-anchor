"""Fetch posts from a Blogger feed (no API key needed for public blogs)."""
import json, re, urllib.request
from bs4 import BeautifulSoup

def fetch_posts(blog="https://masaladeutsch.blogspot.com", n=1, label=None):
    path = f"/feeds/posts/default/-/{label}" if label else "/feeds/posts/default"
    url = f"{blog}{path}?alt=json&max-results={n}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    feed = json.load(urllib.request.urlopen(req, timeout=30))["feed"]
    out = []
    for e in feed.get("entry", []):
        soup = BeautifulSoup(e["content"]["$t"], "html.parser")
        for t in soup(["script", "style", "table", "figure", "img"]):
            t.decompose()
        text = re.sub(r"\n{2,}", "\n\n", soup.get_text("\n")).strip()
        link = next(l["href"] for l in e["link"] if l["rel"] == "alternate")
        out.append({"title": e["title"]["$t"], "url": link, "text": text,
                    "published": e["published"]["$t"][:10]})
    return out
