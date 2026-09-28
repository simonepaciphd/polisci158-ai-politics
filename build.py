"""Build the POLISCI 158 session-review site from sessions/*.md into docs/ (GitHub Pages, served from /docs).
Each session becomes a Quarto reveal.js deck (generated .qmd in _build/, rendered self-contained); build.py writes
the index page itself.

    python build.py              public build: only sessions with status prep or reviewed -> docs/
    python build.py --preview    every session, drafts included and bannered -> _preview/ (git-ignored)

The Markdown in sessions/ is the only content source. This script holds the schedule, interface copy, styles and
checks, never session content. It stops with an error, and writes nothing, when a check fails:
  - a session file is missing, its front matter is incomplete, or its date disagrees with SCHEDULE
  - a restricted source appears in public text (RESTRICTED below: Canvas-only material, unpublished work, local files)
  - a linked list item has no provenance comment ("<!-- from: ... -->")
  - a link is not absolute http(s), or template placeholder text is left in
Needs Python 3.9+, Quarto 1.10+, pandoc 3.x on PATH (used by --check), and beautifulsoup4.
Links are checked separately: python check_links.py
"""
import datetime as dt, html, pathlib, re, shutil, subprocess, sys

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("build: beautifulsoup4 is missing (pip install beautifulsoup4)")

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "sessions"
COURSE_LINE = "POLISCI 158 · AI & Politics · Stanford · Fall 2026"
SITE_TITLE = "Session guide: the politics track"

# Politics-track sessions of the 158 syllabus (v3): session number -> date. Tech-track sessions are out of scope.
SCHEDULE = {1: "2026-09-23", 2: "2026-09-28", 4: "2026-10-05", 6: "2026-10-12", 8: "2026-10-19",
            10: "2026-10-26", 12: "2026-11-02", 14: "2026-11-09", 16: "2026-11-16"}
TITLES = {1: "Introduction", 2: "Demand Side I: Labor Markets, Productivity, and Automation",
          4: "Demand Side II: Firms, Platforms, and Lobbying",
          6: "Demand Side III: Public Opinion and the Information Environment",
          8: "Supply Side I: Politicians, Campaigns, and Elections",
          10: "Supply Side II: Public Institutions and Governance Capacity", 12: "Data Centers",
          14: "US–China Competition", 16: "AI Sovereignty"}
STATUSES = ("draft", "prep", "reviewed")
PUBLIC = ("prep", "reviewed")
REQUIRED = ("session", "date", "title", "status", "based_on")

# Public text must never cite these. Case-insensitive regexes, checked after maintainer comments are stripped.
RESTRICTED = [
    r"canvas", r"dropbox", r"file:", r"\.pptx?\b", r"\.docx?\b",
    r"manuscript", r"\bR&R\b", r"reviewer", r"under review", r"\bsubmission\b",
    r"pressly", r"russel\b", r"g3o.{0,20}draft",
]
PLACEHOLDERS = [r"example\.org", r"Session title as in", r"Question one", r"What to look for\.", r"Two to four sentences"]

UI = {"contents": "Sessions", "soon": "coming soon", "prep": "prep", "reviewed": "prep and review",
      "draft_banner": "Preview only. This deck is a draft and is not published.",
      "draft_short": "Draft preview, not published",
      "project": "Final project guide →",
      "based_on": "Adapted from", "back": "All sessions"}

errors, warnings = [], []


def parse(path):
    raw = path.read_bytes().decode("utf-8-sig")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", raw, re.S)
    if not m:
        errors.append(f"{path.name}: no front matter")
        return None
    meta = {}
    for line in m.group(1).splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()
        if line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    body = raw[m.end():]
    for k in REQUIRED:
        if not meta.get(k):
            errors.append(f"{path.name}: front matter lacks '{k}'")
    if errors:
        return None
    n = int(meta["session"])
    if n not in SCHEDULE:
        errors.append(f"{path.name}: session {n} is not a politics-track session")
    elif meta["date"] != SCHEDULE[n]:
        errors.append(f"{path.name}: date {meta['date']} disagrees with the syllabus ({SCHEDULE[n]})")
    if meta["status"] not in STATUSES:
        errors.append(f"{path.name}: status '{meta['status']}' is not one of {STATUSES}")

    # provenance: every linked list item carries a from-comment (checked on the raw text, before stripping)
    for i, line in enumerate(body.splitlines(), 1):
        if re.match(r"\s*[-*] ", line) and re.search(r"\]\(", line) and "<!-- from:" not in line:
            errors.append(f"{path.name}:{i}: linked item without a provenance comment")
    public = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for pat in RESTRICTED:
        for mm in re.finditer(pat, public, re.I):
            ln = public[:mm.start()].count("\n") + 1
            errors.append(f"{path.name}: restricted source pattern '{pat}' in public text (body line ~{ln})")
    for pat in PLACEHOLDERS:
        if re.search(pat, public):
            errors.append(f"{path.name}: template placeholder left in ('{pat}')")
    for url in re.findall(r"\]\(([^)\s]+)", public):
        if not re.match(r"https?://", url):
            errors.append(f"{path.name}: link '{url}' is not an absolute http(s) URL")
    return {"n": n, "meta": meta, "md": public, "file": path.name, "slug": f"s{n:02d}"}


def to_html(md, prefix):
    try:
        r = subprocess.run(["pandoc", "-f", "gfm", "-t", "html5", f"--id-prefix={prefix}-"],
                           input=md.encode("utf-8"), capture_output=True, check=True)
    except FileNotFoundError:
        sys.exit("build: pandoc is not on PATH")
    except subprocess.CalledProcessError as e:
        sys.exit(f"build: pandoc failed on {prefix}: {e.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8")


def drop_empty_sections(soup):
    """Remove h3 headings with nothing under them, then h2 sections left with nothing but headings."""
    for level, stops in (("h3", ("h2", "h3")), ("h2", ("h2",))):
        for h in soup.find_all(level):
            sib, content = h.next_sibling, False
            while sib is not None and getattr(sib, "name", None) not in stops:
                if getattr(sib, "name", None) or str(sib).strip():
                    content = True
                sib = sib.next_sibling
            if not content:
                h.decompose()


def md_sections(md):
    """Split session Markdown into [(h2, lines, [(h3, lines), ...]), ...], dropping headings with no content."""
    out, h2, h3 = [], None, None
    for line in md.splitlines():
        if line.startswith("## "):
            h2 = [line[3:].strip(), [], []]
            out.append(h2)
            h3 = None
        elif line.startswith("### ") and h2 is not None:
            h3 = [line[4:].strip(), []]
            h2[2].append(h3)
        elif h3 is not None:
            h3[1].append(line)
        elif h2 is not None:
            h2[1].append(line)
    has = lambda lines: any(l.strip() for l in lines)
    result = []
    for title, lines, subs in out:
        subs = [(t, l) for t, l in subs if has(l)]
        if has(lines) or subs:
            result.append((title, lines, subs))
    return result


CARDINAL = "#8c1515"                             # 157 deck theme dk1; section and title slides


def yq(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_qmd(s, prev_s, next_s):
    """One reveal.js deck: title, a slide per h2 without subsections, a section slide plus a slide per h3 otherwise."""
    m = s["meta"]
    sub = f"Session {s['n']} · {when(m['date'])}" + (f" · {UI['draft_short']}" if m["status"] == "draft" else "")
    head = ["---", f"title: {yq(m['title'])}", f"subtitle: {yq(sub)}", f"author: {yq(COURSE_LINE)}", "lang: en",
            "format:", "  revealjs:", "    theme: [default, theme.scss]", "    slide-number: true",
            "    scrollable: true", "    link-external-newwindow: true",
            "    hash-type: number", "    controls: true", "    progress: true",
            f"    footer: {yq('Stanford University · [' + UI['back'] + '](index.html)')}",
            f"title-slide-attributes:", f"  data-background-color: {yq(CARDINAL)}", "---", ""]
    body = []
    sections = md_sections(s["md"])
    body += ["## Roadmap {.roadmap}", ""] + [f"1. {t}" for t, _, _ in sections] + [""]
    for title, lines, subs in sections:
        if subs:
            body += [f'# {title} {{.section background-color="{CARDINAL}"}}', ""]
            if any(l.strip() for l in lines):
                body += lines + [""]
            for t, l in subs:
                n_items = sum(1 for x in l if re.match(r"\s*[-*] ", x))
                cls = " {.dense}" if n_items > 5 else ""
                body += [f"## {t}{cls}", ""] + l + [""]
        else:
            body += [f"## {title}", ""] + lines + [""]
    pager = []
    if prev_s:
        pager.append(f'[← {prev_s["meta"]["title"]}]({prev_s["slug"]}.html)')
    if next_s:
        pager.append(f'[{next_s["meta"]["title"]} →]({next_s["slug"]}.html)')
    body += ["## About this deck", "", f'{UI["based_on"]} POLISCI {m["based_on"]}.', "",
             '::: {.provenance}', FOOTER_MD, ":::", ""]
    if pager:
        body += ['::: {.pager}'] + [f"{p}  " for p in pager] + [":::", ""]
    return "\n".join(head + body)


def when(date):
    d = dt.date.fromisoformat(date)
    return d.strftime("%a, %b ") + str(d.day)


def page(title, nav, main, banner=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
{FONTS}
<style>{CSS}</style>
</head>
<body>
<div class="layout">
<header class="site">
<p><a href="index.html">{html.escape(COURSE_LINE)}</a></p>
<p class="site-title">{html.escape(SITE_TITLE)}</p>
{banner}
</header>
<nav aria-label="{UI['contents']}">
<p class="nav-group">{UI['contents']}</p>
{nav}
</nav>
<main>
{main}
</main>
</div>
</body>
</html>
"""


def nav_html(sessions, shown, current=None):
    items = []
    for s in sessions:
        label = f"{s['n']} · {html.escape(s['meta']['title'])}"
        if s["slug"] in shown:
            cur = ' aria-current="page"' if s["slug"] == current else ""
            items.append(f'<li><a href="{s["slug"]}.html"{cur}>{label}</a></li>')
        else:
            items.append(f'<li><span class="muted">{label}</span></li>')
    return "<ul>\n" + "\n".join(items) + "\n</ul>"


def main():
    if "--check" in sys.argv[1:]:                # validate named files only, write nothing: python build.py --check s04
        wanted = tuple(a for a in sys.argv[1:] if not a.startswith("--"))
        for p in sorted(SRC.glob("s[0-9][0-9]-*.md")):
            if p.name.startswith(wanted):
                s = parse(p)
                if s:
                    drop_empty_sections(BeautifulSoup(to_html(s["md"], s["slug"]), "html.parser"))
                    print(f"checked {p.name}")
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        sys.exit(1 if errors else 0)
    preview = "--preview" in sys.argv[1:]
    out = ROOT / ("_preview" if preview else "docs")
    files = sorted(p for p in SRC.glob("s[0-9][0-9]-*.md"))
    sessions = [s for s in (parse(p) for p in files) if s]
    have = {s["n"] for s in sessions}
    for n in SCHEDULE:
        if n not in have:                        # not drafted yet: listed as coming soon under its syllabus title
            warnings.append(f"no session file yet for session {n}")
            sessions.append({"n": n, "meta": {"title": TITLES[n], "date": SCHEDULE[n], "status": "draft"},
                             "md": "", "file": "(none)", "slug": f"s{n:02d}", "stub": True})
            have.add(n)
    if len({s["n"] for s in sessions}) != len(sessions):
        errors.append("two files claim the same session number")
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        sys.exit(f"build: {len(errors)} error(s); nothing written")
    sessions.sort(key=lambda s: s["n"])
    shown = [s for s in sessions if not s.get("stub") and (preview or s["meta"]["status"] in PUBLIC)]
    shown_slugs = {s["slug"] for s in shown}

    decks = {}                                   # name -> self-contained reveal.js HTML rendered by Quarto
    work = ROOT / "_build"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    shutil.copy(ROOT / "theme.scss", work / "theme.scss")
    # a website project so all decks share one copy of the reveal.js libraries (site_libs/)
    (work / "_quarto.yml").write_text("project:\n  type: website\n  output-dir: _site\nwebsite:\n  title: POLISCI 158\n",
                                      encoding="utf-8", newline="\n")
    for i, s in enumerate(shown):
        prev_s, next_s = (shown[i - 1] if i else None), (shown[i + 1] if i + 1 < len(shown) else None)
        (work / f'{s["slug"]}.qmd').write_text(to_qmd(s, prev_s, next_s), encoding="utf-8", newline="\n")
    site = work / "_site"
    if shown:
        quarto = shutil.which("quarto") or r"C:\Program Files\Quarto\bin\quarto.exe"
        try:
            r = subprocess.run([quarto, "render", "--quiet"], cwd=work,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            sys.exit("build: quarto is not installed (winget install Posit.Quarto)")
        if r.returncode:
            errors.append(f"quarto render failed: {(r.stderr or r.stdout).strip()[-800:]}")
        for s in shown:
            out_html = site / f'{s["slug"]}.html'
            if out_html.exists():
                decks[out_html.name] = out_html.read_text(encoding="utf-8")
            elif not r.returncode:
                errors.append(f'{s["file"]}: quarto produced no {out_html.name}')
    rendered = {}

    rows, slide_files = [], []
    for s in sessions:
        m, st = s["meta"], s["meta"]["status"]
        title = html.escape(m["title"])
        slides = f'slides/{s["slug"]}-slides.html'   # class slides (speaker notes stripped), optional per session
        has_slides = s["slug"] in shown_slugs and (ROOT / slides).exists()
        if has_slides:
            slide_files.append(slides)
        link = (f'<a href="{slides}">{title}</a>' if has_slides
                else f'<a href="{s["slug"]}.html">{title}</a>' if s["slug"] in shown_slugs else title)
        state = (f'<a href="{s["slug"]}.html">{UI[st]}</a>' if st in PUBLIC
                 else "draft (preview)" if preview and not s.get("stub") else UI["soon"])
        rows.append(f"<tr><td>{s['n']}</td><td>{when(m['date'])}</td><td>{link}</td><td>{state}</td></tr>")
    # the project guide goes public only once Simone approves it: an empty project/PUBLISH marker; previews always show it
    has_project = (ROOT / "project" / "index.html").exists() and (preview or (ROOT / "project" / "PUBLISH").exists())
    if (ROOT / "project" / "index.html").exists() and not has_project:
        warnings.append("project/ staged but not approved for publication (no project/PUBLISH); left out of docs/")
    project_line = (f'<p class="project-link"><a href="project/index.html">{UI["project"]}</a></p>\n'
                    if has_project else "")
    index_main = (f"<h1>{html.escape(SITE_TITLE)}</h1>\n{INTRO}\n{project_line}"
                  '<div class="table-wrap"><table><thead><tr><th>#</th><th>Date</th><th>Session</th><th>Status</th>'
                  f"</tr></thead><tbody>\n{chr(10).join(rows)}\n</tbody></table></div>\n{FOOTER}")
    rendered["index.html"] = page(f"{SITE_TITLE} · POLISCI 158", nav_html(sessions, shown_slugs), index_main)

    # internal links must land on a page we are writing (decks: only the links we put in, i.e. the pager and footer)
    built = set(rendered) | set(decks)
    for name, text in rendered.items():
        for a in BeautifulSoup(text, "html.parser").find_all("a", href=True):
            h = a["href"]
            if (h.startswith("project/") and has_project) or h in slide_files:
                continue
            if not h.startswith(("http", "#", "mailto:", "data:")) and h.split("#")[0] not in built:
                errors.append(f"{name}: internal link to {h} which is not built")
    for s in shown:
        for h in re.findall(r"\]\(([\w-]+\.html)\)", (work / f'{s["slug"]}.qmd').read_text(encoding="utf-8")):
            if h not in built:
                errors.append(f'{s["slug"]}.qmd: internal link to {h} which is not built')
    rendered.update(decks)
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        sys.exit(f"build: {len(errors)} error(s); nothing written")

    out.mkdir(exist_ok=True)
    for stale in out.glob("*.html"):            # a session moved back to draft must disappear from the site
        if stale.name not in rendered:
            stale.unlink()
            print(f"removed {stale.relative_to(ROOT)}")
    for d in out.iterdir():                      # generated library folders are replaced wholesale
        if d.is_dir() and (d.name == "site_libs" or d.name.endswith("_files")):
            shutil.rmtree(d)
    if site.exists():
        for d in site.iterdir():
            if d.is_dir():
                shutil.copytree(d, out / d.name)
    if (out / "project").exists():               # static final-project subpage, copied as-is from project/
        shutil.rmtree(out / "project")
    if has_project:
        shutil.copytree(ROOT / "project", out / "project", ignore=shutil.ignore_patterns("PUBLISH"))
    if (out / "slides").exists():                # class slides: only those of sessions on the site
        shutil.rmtree(out / "slides")
    for f in slide_files:
        (out / f).parent.mkdir(exist_ok=True)
        shutil.copy(ROOT / f, out / f)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    for name, text in rendered.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    for s in sessions:
        print(f"  s{s['n']:02d}  {s['meta']['status']:<8}  {'built' if s['slug'] in shown_slugs else 'skipped'}  {s['file']}")
    for w in warnings:
        print("WARNING:", w)
    print(f"wrote {len(rendered)} page(s) to {out.relative_to(ROOT)}/")


# ---------------------------------------------------------------- interface copy (not session content)
INTRO = """<p>One slide deck per session of the politics track of POLISCI 158. Before class, each deck lists what to
read, listen to, or explore. After class, it adds the key takeaways and places to go further. Decks appear as the
quarter goes on; use the arrow keys or swipe to move through the slides. A session's title opens its class slides;
the Status column opens its prep deck.</p>"""
FOOTER_MD = ("Curated by Simone Paci, Stanford University. Drafted with AI assistance (Claude) from the instructor's "
             "course materials and reviewed by the instructor before publication; every external link is checked "
             "before each update.")
FOOTER = f'<p class="provenance">{FOOTER_MD}</p>'

# ---------------------------------------------------------------- styles (tokens shared with the 158 final-project guide)
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,600;'
         '0,700;1,400&amp;family=Source+Serif+4:wght@400;600&amp;display=swap">')
DARK = ("--bg:#16181b; --surface:#1f2226; --fg:#e6e8eb; --muted:#9aa3ad; --line:#30353b; "
        "--accent:#e0858a; --accent-soft:#3a2324; color-scheme:dark;")
LIGHT = ("--bg:#fbf8f4; --surface:#ffffff; --fg:#161719; --muted:#62666c; --line:#e8e1da; "
         "--accent:#8c1515; --accent-soft:#f3e6e6; color-scheme:light;")
CSS = """
:root { %LIGHT%
  --font-heading:"Source Serif 4", Georgia, serif;
  --font-body:"Source Sans 3", system-ui, -apple-system, "Segoe UI", sans-serif; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { %DARK% } }
:root[data-theme="dark"] { %DARK% }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:17px/1.6 var(--font-body); padding-inline:16px; -webkit-text-size-adjust:100%; }
h1, h2, h3 { line-height:1.25; text-wrap:balance; }
h1, h2 { font-family:var(--font-heading); font-weight:600; }
h1 { font-size:2rem; margin:0 0 1rem; }
h2 { font-size:1.4rem; margin:2.25rem 0 .75rem; }
h3 { font-weight:600; font-size:1.08rem; margin:1.5rem 0 .5rem; }
a { color:var(--accent); text-underline-offset:.15em; }
:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
li { margin:.4rem 0; }
.layout { display:grid; grid-template-columns:16rem minmax(0, 44rem); column-gap:3rem; justify-content:center; padding-block:2rem 4rem; }
main { min-width:0; }
.site { grid-column:1 / -1; border-bottom:1px solid var(--line); padding-bottom:1rem; margin-bottom:2rem; }
.site p { margin:0; }
.site p:first-child a { color:var(--muted); font-size:.85rem; letter-spacing:.04em; text-decoration:none; }
.site-title { font-family:var(--font-heading); font-size:1.5rem; font-weight:600; margin-top:.2rem !important; }
.banner { margin-top:.75rem !important; padding-left:.75rem; border-left:3px solid var(--accent); }
.layout > nav { position:sticky; top:1rem; align-self:start; max-height:calc(100vh - 2rem); overflow-y:auto; }
nav ul { list-style:none; margin:0; padding:0; }
nav li { margin:0; }
nav li a, nav li span { display:block; padding:.3rem 0 .3rem .75rem; border-left:2px solid transparent; color:var(--fg); text-decoration:none; font-size:.95rem; line-height:1.35; }
nav li a:hover { color:var(--accent); }
nav li a[aria-current="page"] { color:var(--accent); border-left-color:var(--accent); font-weight:600; }
.muted, nav li span.muted { color:var(--muted); }
.nav-group { margin:0 0 .35rem; font-size:.75rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
.kicker { margin:0 0 .25rem; color:var(--muted); font-size:.9rem; letter-spacing:.03em; }
.table-wrap { overflow-x:auto; margin:1rem 0 1.5rem; }
table { border-collapse:collapse; width:100%; font-size:.95rem; }
th, td { padding:.5rem .65rem; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }
thead th { background:var(--surface); font-weight:600; }
.pager { display:flex; justify-content:space-between; gap:1rem; margin-top:3rem; padding-top:1.25rem; border-top:1px solid var(--line); }
.pager a { font-weight:600; text-decoration:none; }
.pager .next { margin-left:auto; text-align:right; }
.provenance { margin-top:2rem; color:var(--muted); font-size:.88rem; }
@media (max-width: 899px) {
  body { font-size:16px; }
  .layout { grid-template-columns:minmax(0, 1fr); padding-block:1.25rem 3rem; }
  .layout > nav { position:static; max-height:none; order:3; border-top:1px solid var(--line); margin-top:2.5rem; padding-top:1rem; }
  .site { margin-bottom:1.5rem; }
  nav li a, nav li span { padding-block:.6rem; }
  .pager { flex-direction:column; gap:.75rem; }
  .pager .next { margin-left:0; text-align:left; }
}
@media print {
  :root, :root:not([data-theme="light"]), :root[data-theme="dark"] { %LIGHT% }
  .layout { display:block; } .layout > nav, .pager { display:none; }
}
""".replace("%LIGHT%", LIGHT).replace("%DARK%", DARK)


if __name__ == "__main__":
    main()
