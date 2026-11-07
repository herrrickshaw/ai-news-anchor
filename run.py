#!/usr/bin/env python3
"""python run.py [--n 1] [--avatar colab_out.mp4] [--portrait portrait.png]"""
import argparse, datetime, pathlib, re
from anchor.fetch import fetch_posts
from anchor.script import write_script
from anchor.tts import speak
from anchor.overlay import make_overlay, make_ticker
from anchor.compose import compose

ap = argparse.ArgumentParser()
ap.add_argument("--blog", default="https://masaladeutsch.blogspot.com")
ap.add_argument("--n", type=int, default=1)
ap.add_argument("--name", default="Sana")
ap.add_argument("--portrait", default="portrait.png")
ap.add_argument("--avatar", help="talking-head mp4 made by colab/avatar_colab.ipynb")
ap.add_argument("--voice", default="en-IN-NeerjaNeural")
ap.add_argument("--out", default="episodes")
a = ap.parse_args()

for post in fetch_posts(a.blog, a.n):
    slug = re.sub(r"[^a-z0-9]+", "-", post["title"].lower())[:50].strip("-")
    d = pathlib.Path(a.out) / slug; d.mkdir(parents=True, exist_ok=True)
    s = write_script(post, a.name)
    (d / "script.txt").write_text(s["script"])
    speak(s["script"], str(d / "audio.mp3"), a.voice)
    make_overlay(s["headline"], f"{a.name.upper()}", datetime.date.today().strftime("%d %b %Y"), path=str(d / "overlay.png"))
    tp, tw = make_ticker(s["ticker"], path=str(d / "ticker.png"))
    out = compose(str(d / "audio.mp3"), str(d / "overlay.png"), tp, tw, str(d / "episode.mp4"),
                  avatar_video=a.avatar, portrait=a.portrait)
    print("DONE", out)
