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
ap.add_argument("--script", choices=["claude", "gemini"], default="claude")
ap.add_argument("--tts", choices=["edge", "gemini"], default="edge")
ap.add_argument("--gemini-portrait", action="store_true", help="generate portrait.png with Gemini first")
ap.add_argument("--veo", action="store_true", help="make the anchor clip with Veo (looped, not lip-synced)")
ap.add_argument("--out", default="episodes")
a = ap.parse_args()

if a.gemini_portrait:
    from anchor import gemini; gemini.portrait(a.portrait)
if a.veo and not a.avatar:
    from anchor import gemini; a.avatar = gemini.veo_idle_clip(a.portrait)

for post in fetch_posts(a.blog, a.n):
    slug = re.sub(r"[^a-z0-9]+", "-", post["title"].lower())[:50].strip("-")
    d = pathlib.Path(a.out) / slug; d.mkdir(parents=True, exist_ok=True)
    s = write_script(post, a.name, engine=a.script)
    (d / "script.txt").write_text(s["script"])
    if a.tts == "gemini":
        try:
            from anchor import gemini; audio = gemini.tts(s["script"], str(d / "audio.wav"))
        except Exception as e:
            print("Gemini TTS failed (%s), using edge-tts" % type(e).__name__)
            audio = speak(s["script"], str(d / "audio.mp3"), a.voice)
    else:
        audio = speak(s["script"], str(d / "audio.mp3"), a.voice)
    make_overlay(s["headline"], f"{a.name.upper()}", datetime.date.today().strftime("%d %b %Y"), path=str(d / "overlay.png"))
    tp, tw = make_ticker(s["ticker"], path=str(d / "ticker.png"))
    out = compose(audio, str(d / "overlay.png"), tp, tw, str(d / "episode.mp4"),
                  avatar_video=a.avatar, portrait=a.portrait)
    print("DONE", out)
