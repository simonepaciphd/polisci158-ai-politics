"""Stage the POLISCI 158 final-project guide as the static subpage project/ of this site.

    python tools/stage_project.py            rebuild project/ from the Dropbox package (rerun whenever the package changes)
    python tools/stage_project.py --check    verify project/ is current with the package; write nothing

Reads (never writes) the package built by sp-final-project-html-handoff/build_guide.py:
    <course>/Assignments/final-project/polisci158-final-project-guide.html
    <course>/Assignments/final-project/polisci158-final-project-package.zip

Writes project/ (owned by this script; replaced wholesale on every run):
    index.html                              the guide, with two interface changes only (see below)
    polisci158-final-project-package.zip    byte copy of the package zip
    *.md, workflows/*.md, docs/*.md         the cleaned Markdown, extracted from the zip (same text the guide embeds)

The guide's download buttons work only through the claude.ai Artifact "downloads" capability (window.claude) and stay
hidden elsewhere. On GitHub Pages this script turns each hidden button into a visible plain link to the file served
next to the page, keeping the button's label. It also adds one "<- Session decks" link above the layout. Nothing else
changes: the script undoes both edits in memory and fails unless the result equals the source guide byte for byte.
"""
import hashlib, html, io, json, pathlib, re, shutil, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "project"
PKG = pathlib.Path(r"C:\Users\spaci\Dropbox\Teaching\POLISCI 158 - Politics and AI\Assignments\final-project")
SRC_HTML = PKG / "polisci158-final-project-guide.html"
SRC_ZIP = PKG / "polisci158-final-project-package.zip"
ZIP_FOLDER = "final-project/"

# interface copy (not guide content)
BACK_LABEL = "\u2190 Session decks"
BACK_HTML = f'<p class="site-back"><a href="../index.html">{html.escape(BACK_LABEL)}</a></p>\n'
BACK_CSS = ("<style>.site-back { max-width:62rem; margin:1rem auto 0; font-size:.85rem; letter-spacing:.04em; }\n"
            ".site-back a { color:var(--muted); text-decoration:none; } .site-back a:hover { color:var(--accent); }\n"
            "@media print { .site-back { display:none; } }</style>\n")
LAYOUT_OPEN = '<body>\n<div class="layout">'
CONTROL = re.compile(r'<p class="page-tools" hidden=""><button class="btn" data-download="([\w-]+)" type="button">'
                     r'([^<]*)</button><span aria-live="polite" class="note"></span></p>')
LINK = '<p class="page-tools"><a class="btn" href="{href}" download="{name}" data-staged="{key}">{label}</a></p>'
LINK_RE = re.compile(r'<p class="page-tools"><a class="btn" href="[^"]*" download="[^"]*" data-staged="([\w-]+)">'
                     r'([^<]*)</a></p>')


def fail(msg):
    sys.exit(f"stage_project: {msg}; nothing written")


def build():
    for p in (SRC_HTML, SRC_ZIP):
        if not p.exists():
            fail(f"missing {p}")
    src = SRC_HTML.read_bytes().decode("utf-8")
    zip_bytes = SRC_ZIP.read_bytes()

    # the files the guide embeds (key -> name, cleaned text)
    m = re.search(r'<script type="application/json" id="guide-files">(.*?)</script>', src, re.S)
    if not m:
        fail("guide-files JSON block not found in the guide")
    embedded = json.loads(m.group(1))

    # the zip: cleaned Markdown in its folder structure
    members = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(ZIP_FOLDER):
                fail(f"zip member outside {ZIP_FOLDER}: {info.filename}")
            rel = info.filename[len(ZIP_FOLDER):]
            if ".." in pathlib.PurePosixPath(rel).parts or not rel.endswith(".md"):
                fail(f"unexpected zip member {info.filename}")
            members[rel] = z.read(info)

    # key -> path inside project/, and the embedded text must equal the zip text
    href = {"zip": SRC_ZIP.name}
    by_name = {pathlib.PurePosixPath(r).name: r for r in members}
    for key, f in embedded.items():
        if key == "zip":
            continue
        rel = by_name.get(f["name"])
        if rel is None:
            fail(f"embedded file {key} ({f['name']}) is not in the zip")
        if members[rel].decode("utf-8") != f["text"]:
            fail(f"embedded text for {key} differs from zip member {rel}")
        href[key] = rel
    if len(href) - 1 != len(members):
        fail(f"{len(members)} zip members but {len(href) - 1} embedded pages")

    # 1) hidden Artifact-only buttons -> plain links
    seen = []

    def to_link(mt):
        key, label = mt.group(1), mt.group(2)
        if key not in href:
            fail(f"download control for unknown key {key}")
        seen.append(key)
        return LINK.format(href=html.escape(href[key]), name=html.escape(pathlib.PurePosixPath(href[key]).name),
                           key=key, label=label)

    out = CONTROL.sub(to_link, src)
    if not seen:
        fail("no download controls found (has build_guide.py changed its markup?)")
    if 'data-download="' in out:
        fail("a download control was left unconverted (markup changed?)")
    missing = set(href) - set(seen)
    if missing:
        fail(f"no download control for {sorted(missing)}")

    # 2) back link above the layout, plus its style
    if out.count(LAYOUT_OPEN) != 1 or out.count("</head>") != 1:
        fail("page frame markers not found exactly once")
    out = out.replace("</head>", BACK_CSS + "</head>", 1)
    out = out.replace(LAYOUT_OPEN, "<body>\n" + BACK_HTML + '<div class="layout">', 1)

    # 3) reversal check: undoing both edits must give the source guide back, byte for byte
    rev = out.replace(BACK_CSS, "", 1).replace(BACK_HTML, "", 1)
    rev = LINK_RE.sub(lambda mt: '<p class="page-tools" hidden=""><button class="btn" data-download="%s" type="button">'
                      '%s</button><span aria-live="polite" class="note"></span></p>' % (mt.group(1), mt.group(2)), rev)
    if rev != src:
        fail("reversal check failed: staged page differs from the guide beyond the two interface edits")

    files = {"index.html": out.encode("utf-8"), SRC_ZIP.name: zip_bytes}
    files.update(members)
    return files, len(seen)


def main():
    files, n = build()
    if "--check" in sys.argv[1:]:
        have = {p.relative_to(OUT).as_posix(): p.read_bytes() for p in OUT.rglob("*") if p.is_file()} if OUT.exists() else {}
        if have != files:
            sys.exit(f"stage_project --check: project/ is stale (differs in {sorted(set(have) ^ set(files)) or 'content'})")
        print(f"stage_project --check: project/ is current ({len(files)} files)")
        return
    if OUT.exists():
        shutil.rmtree(OUT)
    for rel, data in files.items():
        p = OUT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    print(f"source guide sha256 {hashlib.sha256(SRC_HTML.read_bytes()).hexdigest()}")
    print(f"source zip   sha256 {hashlib.sha256(SRC_ZIP.read_bytes()).hexdigest()}")
    print(f"converted {n} download controls; reversal check passed")
    for rel in files:
        print(f"wrote project/{rel} ({len(files[rel]):,} bytes)")


if __name__ == "__main__":
    main()
