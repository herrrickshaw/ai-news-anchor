"""Turn a blog post into a short broadcast script using the local `claude` CLI,
falling back to a plain extractive summary if the CLI is unavailable."""
import json, re, shutil, subprocess

PROMPT = """You are the scriptwriter for an AI news anchor called {name}.
Turn the blog post below into a spoken news bulletin of about {words} words.
Rules: open with a one-line hook, state only facts that are in the post (keep every
number exactly), no headings or bullet points, plain sentences that sound natural read aloud,
close with one line pointing viewers to the full article. Do not invent anything.
Return ONLY JSON: {{"headline": "<max 70 chars>", "ticker": "<one line, max 140 chars>", "script": "<spoken text>"}}

TITLE: {title}

POST:
{text}
"""

def write_script(post, name="Sana", words=170, engine="claude"):
    if engine == "gemini":
        try:
            from anchor import gemini
            return gemini.write_script(PROMPT.format(name=name, words=words, title=post["title"], text=post["text"][:12000]))
        except Exception as e:
            print("Gemini script failed (%s), falling back" % type(e).__name__)
    if shutil.which("claude"):
        try:
            p = PROMPT.format(name=name, words=words, title=post["title"], text=post["text"][:12000])
            r = subprocess.run(["claude", "-p", p], capture_output=True, text=True, timeout=240)
            m = re.search(r"\{.*\}", r.stdout, re.S)
            if m:
                d = json.loads(m.group(0))
                if d.get("script"):
                    return d
        except Exception as e:
            print("claude CLI failed, using fallback:", e)
        else:
            print("WARNING: claude CLI returned no JSON (", r.stdout.strip()[:100], ") - using extractive fallback; run `claude auth login`")
    text = "\n".join(l for l in post["text"].splitlines()
                     if l.strip() and not l.strip().startswith("\u2190") and not re.match(r"^[A-Za-z &]+ \u00b7 \d", l.strip()))
    text = text.replace(post["title"], "", 1)
    sents = re.split(r"(?<=[.!?])\s+", text)
    body, n = [], 0
    for s in sents:
        if n + len(s.split()) > words: break
        body.append(s); n += len(s.split())
    t = post["title"]; head = t if len(t) <= 70 else t[:t.rfind(" ", 0, 67)] + "..."
    return {"headline": head, "ticker": t[:140],
            "script": f"{post['title']}. " + " ".join(body) + " Read the full article on the blog."}
