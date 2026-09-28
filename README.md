# POLISCI 158 · AI & Politics · session guide (politics track)

Public, student-facing pages for the politics-track sessions of POLISCI 158 (Stanford, Fall 2026): what to prepare before each session and what to review after it.
Site: https://simonepaciphd.github.io/polisci158-ai-politics/ (GitHub Pages, served from `docs/`).

## Maintaining

```
sessions/sNN-slug.md    one file per session, the only content source (template: sessions/_TEMPLATE.md)
build.py                sessions/ -> docs/ (public) or _preview/ (--preview, drafts included)
check_links.py          checks every external link; run before each publish
tools/stage_project.py  project/ from the final-project package (set POLISCI158_PACKAGE to its folder first)
docs/                   generated site; do not edit by hand
```

Weekly cycle, per session:

1. **Prep.** Draft or revise `sessions/sNN-*.md`, set `status: prep` once approved.
2. `python check_links.py sNN` (no DEAD links; open MANUAL ones in a browser), then `python build.py`.
3. Commit `sessions/` and `docs/` together; push.
4. **Review.** After the session, fill in "After class", set `status: reviewed`, repeat steps 2–3.

`status: draft` pages never reach `docs/`; moving a page back to draft removes it on the next build.
`build.py` refuses to write when a linked item lacks a `<!-- from: ... -->` provenance comment, when public text cites a restricted source (Canvas-only material, unpublished work, local files), or when template text is left in.

Requires Python 3.9+, pandoc 3.x, beautifulsoup4.
