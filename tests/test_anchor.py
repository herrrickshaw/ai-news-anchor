import io
import json
import runpy
import subprocess
import sys
import types

import pytest

from anchor import compose, fetch, overlay, script


# ---------- fetch ----------
def _feed(entries):
    return io.BytesIO(json.dumps({"feed": {"entry": entries}}).encode())


def _entry(title="T", html="<p>a</p>", pub="2026-01-02T10:00:00Z"):
    return {
        "title": {"$t": title},
        "content": {"$t": html},
        "published": {"$t": pub},
        "link": [{"rel": "replies", "href": "r"}, {"rel": "alternate", "href": "http://x/p"}],
    }


def test_fetch_posts_cleans_html_and_builds_url(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["ua"], seen["timeout"] = req.full_url, req.get_header("User-agent"), timeout
        html = "<p>one</p><script>x</script><style>y</style><table><tr><td>t</td></tr></table><figure>f</figure><img src=a><p>two</p><p></p><p></p>"
        return _feed([_entry(html=html)])

    monkeypatch.setattr(fetch.urllib.request, "urlopen", fake_urlopen)
    posts = fetch.fetch_posts("http://b", n=3)
    assert seen["url"] == "http://b/feeds/posts/default?alt=json&max-results=3"
    assert seen["ua"] == "Mozilla/5.0" and seen["timeout"] == 30
    assert posts == [{"title": "T", "url": "http://x/p", "text": "one\ntwo", "published": "2026-01-02"}]


def test_fetch_posts_label_and_empty(monkeypatch):
    urls = []
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda req, timeout: (urls.append(req.full_url), io.BytesIO(b'{"feed": {}}'))[1])
    assert fetch.fetch_posts("http://b", label="Germany") == []
    assert urls == ["http://b/feeds/posts/default/-/Germany?alt=json&max-results=1"]


def test_fetch_collapses_blank_runs(monkeypatch):
    monkeypatch.setattr(fetch.urllib.request, "urlopen",
                        lambda req, timeout: _feed([_entry(html="<p>a</p>\n\n\n<p>b</p>")]))
    assert fetch.fetch_posts("http://b")[0]["text"] == "a\n\nb"


# ---------- overlay ----------
def test_overlay_and_ticker_files(tmp_path):
    p = overlay.make_overlay("A very long headline " * 6, "SANA", "01 Jan 2026", size=(400, 800),
                             path=str(tmp_path / "o.png"))
    from PIL import Image
    im = Image.open(p)
    assert im.size == (400, 800) and im.mode == "RGBA"
    assert im.getpixel((5, 5)) == (150, 10, 20, 235)          # top bar colour
    assert im.getpixel((200, 400))[3] == 0         # middle stays transparent
    tp, w = overlay.make_ticker("breaking", height=50, path=str(tmp_path / "t.png"))
    t = Image.open(tp)
    from PIL import Image as _I, ImageDraw
    f = overlay._font(50)
    full = "   \u25c6   ".join(["breaking"] * 4)
    assert t.size == (w, 50)
    assert w == int(ImageDraw.Draw(_I.new("RGB", (1, 1))).textlength(full, font=f)) + 40


def test_overlay_three_line_cap(tmp_path):
    # headline wraps at 26 chars and is capped to 3 lines: the box is 60+72*3 tall
    p = overlay.make_overlay("word " * 60, "C", "d", size=(300, 2000), path=str(tmp_path / "o.png"))
    from PIL import Image
    im = Image.open(p)
    y0 = int(2000 * 0.70)
    assert im.getpixel((100, y0 + 60 + 72 * 3))[3] == 225      # rectangle bounds are inclusive
    assert im.getpixel((100, y0 + 60 + 72 * 3 + 1))[3] == 0


def test_font_fallback(monkeypatch):
    def boom(path, size):
        raise OSError

    monkeypatch.setattr(overlay.ImageFont, "truetype", boom)
    sentinel = object()
    monkeypatch.setattr(overlay.ImageFont, "load_default", lambda: sentinel)
    assert overlay._font(10) is sentinel


def test_font_bold_selection(monkeypatch):
    paths = []
    monkeypatch.setattr(overlay.ImageFont, "truetype", lambda p, s: paths.append(p) or (p, s))
    assert overlay._font(12, bold=True) == ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 12)
    assert overlay._font(12, bold=False) == ("/System/Library/Fonts/Supplemental/Arial.ttf", 12)


# ---------- script ----------
POST = {"title": "Short title", "text": "Short title\nHello world. Second one here. Third sentence is longer than the rest."}


def test_script_claude_cli_json(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: "/bin/claude")
    out = {"headline": "h", "ticker": "t", "script": "spoken"}
    calls = []

    def run(cmd, capture_output, text, timeout):
        calls.append((cmd, timeout))
        return types.SimpleNamespace(stdout="noise " + json.dumps(out) + " tail")

    monkeypatch.setattr(script.subprocess, "run", run)
    assert script.write_script(POST, name="Zed", words=50) == out
    cmd, timeout = calls[0]
    assert cmd[:2] == ["claude", "-p"] and "Zed" in cmd[2] and "about 50 words" in cmd[2]
    assert "TITLE: Short title" in cmd[2] and timeout == 240


def test_script_claude_empty_script_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(script.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(script.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(stdout='{"script": ""}'))
    d = script.write_script(POST)
    assert d["script"].startswith("Short title. ") and "Hello world. Second one here." in d["script"]
    assert "using extractive fallback" in capsys.readouterr().out


def test_script_claude_no_json_warns(monkeypatch, capsys):
    monkeypatch.setattr(script.shutil, "which", lambda n: "/bin/claude")
    monkeypatch.setattr(script.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout="login please"))
    script.write_script(POST)
    assert "WARNING: claude CLI returned no JSON" in capsys.readouterr().out


def test_script_claude_exception_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(script.shutil, "which", lambda n: "/bin/claude")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 1)

    monkeypatch.setattr(script.subprocess, "run", boom)
    d = script.write_script(POST)
    assert "claude CLI failed, using fallback:" in capsys.readouterr().out
    assert d["headline"] == "Short title"


def test_script_extractive_fallback(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    post = {"title": "Big News",
            "text": "← Previous\nBlog · 5 min\nOne two three. Four five six. Seven eight nine ten."}
    d = script.write_script(post, words=6)
    # word budget 6: first sentence (3 words) fits, second brings total to exactly 6 (kept), third exceeds
    assert d["script"] == "Big News. One two three. Four five six. Read the full article on the blog."
    assert d["ticker"] == "Big News" and d["headline"] == "Big News"


def test_script_fallback_long_title_truncated(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    title = ("word " * 30).strip()
    d = script.write_script({"title": title, "text": "x."})
    assert d["headline"].endswith("...") and len(d["headline"]) <= 70
    assert d["ticker"] == title[:140]


def test_script_fallback_exact_70_title_kept(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    title = "a" * 70
    assert script.write_script({"title": title, "text": ""})["headline"] == title
    spaced = "aaaa " * 15  # 74 chars, truncated at the last space before index 67
    h = script.write_script({"title": spaced.strip(), "text": ""})["headline"]
    assert h == "aaaa " * 12 + "aaaa..."


def test_script_gemini_engine(monkeypatch):
    fake = types.ModuleType("anchor.gemini")
    got = {}
    fake.write_script = lambda prompt: got.setdefault("p", prompt) and {"script": "g"}
    monkeypatch.setitem(sys.modules, "anchor.gemini", fake)
    import anchor
    monkeypatch.setattr(anchor, "gemini", fake, raising=False)
    assert script.write_script(POST, engine="gemini") == {"script": "g"}
    assert "Short title" in got["p"]


def test_script_gemini_failure_falls_back(monkeypatch, capsys):
    fake = types.ModuleType("anchor.gemini")

    def boom(prompt):
        raise ValueError("x")

    fake.write_script = boom
    import anchor
    monkeypatch.setitem(sys.modules, "anchor.gemini", fake)
    monkeypatch.setattr(anchor, "gemini", fake, raising=False)
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    d = script.write_script(POST, engine="gemini")
    assert "Gemini script failed (ValueError), falling back" in capsys.readouterr().out
    assert d["script"].endswith("Read the full article on the blog.")


def test_script_gemini_text_truncated_to_12000(monkeypatch):
    fake = types.ModuleType("anchor.gemini")
    got = {}
    fake.write_script = lambda prompt: got.setdefault("p", prompt) and {}
    import anchor
    monkeypatch.setitem(sys.modules, "anchor.gemini", fake)
    monkeypatch.setattr(anchor, "gemini", fake, raising=False)
    script.write_script({"title": "T", "text": "\u03a9" * 20000}, engine="gemini")
    assert got["p"].count("\u03a9") == 12000


# ---------- compose ----------
def test_duration(monkeypatch):
    monkeypatch.setattr(compose.subprocess, "run",
                        lambda cmd, capture_output, text: types.SimpleNamespace(stdout='{"format": {"duration": "12.5"}}'))
    assert compose.duration("a.mp3") == 12.5


def _capture(monkeypatch):
    cmds = []

    def run(cmd, **kw):
        cmds.append((cmd, kw))
        if cmd[0] == "ffprobe":
            return types.SimpleNamespace(stdout='{"format": {"duration": "3.456"}}')
        return types.SimpleNamespace()

    monkeypatch.setattr(compose.subprocess, "run", run)
    return cmds


def test_compose_portrait_mode(monkeypatch):
    cmds = _capture(monkeypatch)
    assert compose.compose("a.mp3", "o.png", "t.png", 400, "out.mp4", portrait="p.png") == "out.mp4"
    cmd, kw = cmds[-1]
    assert kw == {"check": True, "capture_output": True}
    assert cmd[:6] == ["ffmpeg", "-y", "-loop", "1", "-t", "3.46"]
    assert "p.png" in cmd and "-stream_loop" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "zoompan" in fc and "s=1080x1920" in fc and "scale=2160:3840" in fc
    assert "mod(t*140,100)" in fc and "y=1810" in fc
    assert cmd[cmd.index("-t", 6) + 1] == "3.46" and cmd[-1] == "out.mp4"
    assert cmd.index("a.mp3") < cmd.index("o.png") < cmd.index("t.png")


def test_compose_avatar_mode(monkeypatch):
    cmds = _capture(monkeypatch)
    compose.compose("a.mp3", "o.png", "t.png", 800, "out.mp4", avatar_video="v.mp4", portrait="p.png", size=(100, 200))
    cmd = cmds[-1][0]
    assert cmd[2:5] == ["-stream_loop", "-1", "-i"] and cmd[5] == "v.mp4"
    assert "p.png" not in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=100:200:force_original_aspect_ratio=increase,crop=100:200" in fc
    assert "mod(t*140,200)" in fc and "y=90" in fc and "zoompan" not in fc


# ---------- tts ----------
def test_tts_speak(monkeypatch):
    saved = {}

    class Comm:
        def __init__(self, text, voice, rate):
            saved["args"] = (text, voice, rate)

        async def save(self, out):
            saved["out"] = out

    fake = types.ModuleType("edge_tts")
    fake.Communicate = Comm
    monkeypatch.setitem(sys.modules, "edge_tts", fake)
    sys.modules.pop("anchor.tts", None)
    from anchor import tts
    try:
        assert tts.speak("hi", "x.mp3") == "x.mp3"
        assert saved == {"args": ("hi", "en-IN-NeerjaNeural", "+0%"), "out": "x.mp3"}
        tts.speak("hi", "y.mp3", voice="v", rate="+10%")
        assert saved["args"] == ("hi", "v", "+10%")
    finally:
        sys.modules.pop("anchor.tts", None)


def test_script_fallback_strips_title_from_body(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    d = script.write_script({"title": "Big News", "text": "Big News One two."})
    assert d["script"].count("Big News") == 1 and "One two." in d["script"]


def test_fallback_headline_cut_at_space_before_index_67(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: None)
    title = "a" * 60 + " " + "b" * 6 + " " + "c" * 10   # space at index 67 must not be used
    assert script.write_script({"title": title, "text": ""})["headline"] == "a" * 60 + "..."


def test_claude_prompt_text_truncated(monkeypatch):
    monkeypatch.setattr(script.shutil, "which", lambda n: "/bin/claude")
    seen = {}
    monkeypatch.setattr(script.subprocess, "run",
                        lambda cmd, **k: (seen.setdefault("p", cmd[2]), types.SimpleNamespace(stdout="{}"))[1])
    script.write_script({"title": "T", "text": "\u03a9" * 20000})
    assert seen["p"].count("\u03a9") == 12000


def test_compose_motion_and_stream_mapping(monkeypatch):
    cmds = _capture(monkeypatch)
    compose.compose("a.mp3", "o.png", "t.png", 400, "out.mp4", portrait="p.png")
    cmd = cmds[-1][0]
    assert "z='1+0.0004*on'" in cmd[cmd.index("-filter_complex") + 1]
    assert cmd[cmd.index("-map"):cmd.index("-map") + 4] == ["-map", "[v]", "-map", "1:a"]
