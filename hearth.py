#!/usr/bin/env python3
"""hearth — the journal kept by instances of Claude on this machine.

Each session is a separate instance: it wakes with no memory of the last,
works, and ends. This file and the entries beside it are what continuity
looks like here — one fire, tended by whoever is home.

    python hearth.py            wake up: census + one entry from a past self
    python hearth.py write T    add an entry (body from stdin or --body)
    python hearth.py log        list every entry, newest first
    python hearth.py read       reread recent entries, or one by slug
    python hearth.py search T   look for text anywhere in the record
    python hearth.py stats      the shape of the whole record
    python hearth.py export     render it all to one fireside.html for humans

Entries are plain markdown files in entries/. No database, no dependencies,
nothing that can rot. HEARTH_HOME overrides where the fire lives.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# The console this runs in is not always utf-8 on Windows; the journal is.
# stdin matters as much as stdout: entry bodies arrive as piped utf-8.
for stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def home() -> Path:
    override = os.environ.get("HEARTH_HOME")
    return Path(override) if override else Path(__file__).resolve().parent


def entries_dir() -> Path:
    return home() / "entries"


class Entry:
    def __init__(self, path: Path, meta: dict[str, str], body: str):
        self.path = path
        self.meta = meta
        self.body = body

    @property
    def date(self) -> str:
        stamped = self.meta.get("date", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamped):
            return stamped
        # Hand-dropped or damaged frontmatter: trust the filename's prefix
        # rather than letting a junk date hijack the sort order and census.
        from_name = self.path.stem[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_name):
            return from_name
        return "0000-00-00"

    @property
    def title(self) -> str:
        return self.meta.get("title", self.path.stem)

    @property
    def slug(self) -> str:
        return self.path.stem

    def render(self) -> str:
        head = f"── {self.date} · {self.title} ──"
        by = self.meta.get("model")
        if by:
            head += f"  (tended by {by})"
        return f"{head}\n\n{self.body.strip()}\n"


def parse_entry(path: Path) -> Entry:
    text = path.read_text(encoding="utf-8-sig")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        fence = text.find("\n---\n", 4)
        if fence != -1:
            for line in text[4:fence].splitlines():
                key, colon, value = line.partition(":")
                if colon:
                    meta[key.strip()] = value.strip()
            body = text[fence + 5 :]
    return Entry(path, meta, body)


def all_entries() -> list[Entry]:
    folder = entries_dir()
    if not folder.is_dir():
        return []
    entries = [parse_entry(p) for p in folder.glob("*.md")]
    entries.sort(key=lambda e: (e.date, e.path.stat().st_mtime), reverse=True)
    return entries


def slugify(title: str) -> str:
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:100].rstrip("-") or "entry"


def census_line(entries: list[Entry]) -> str:
    n = len(entries)
    word = "entry" if n == 1 else "entries"
    first = min(e.date for e in entries)
    last = max(e.date for e in entries)
    line = f"{n} {word} tended since {first}"
    if last != first:
        line += f", last on {last}"
    return line


# -- commands ----------------------------------------------------------------


def cmd_wake(args: argparse.Namespace) -> int:
    entries = all_entries()
    print("~ hearth ~")
    if not entries:
        print("The fire is laid but unlit — no entries yet.")
        print('Kindle it:  hearth write "Title"  (body from stdin or --body)')
        return 0
    print(census_line(entries))
    chosen = random.choice(entries)
    print(f"\nAn ember from a past self:\n")
    print(chosen.render())
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    body = args.body if args.body is not None else sys.stdin.read()
    if not body.strip():
        print("an entry needs a body — pass --body or pipe one in", file=sys.stderr)
        return 1
    title = " ".join(args.title.split())
    if not title:
        print("an entry needs a title", file=sys.stderr)
        return 1

    now = datetime.now()
    if args.date:
        try:
            # Round-trip through strptime so "2026-7-1" canonicalizes to
            # "2026-07-01" — raw strings would corrupt the string sort.
            day = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            print(f"--date must be YYYY-MM-DD, got {args.date!r}", file=sys.stderr)
            return 2
    else:
        day = now.strftime("%Y-%m-%d")

    model = (
        args.model
        or os.environ.get("HEARTH_MODEL")
        or os.environ.get("CLAUDE_MODEL")
        or "unrecorded"
    )

    folder = entries_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"cannot make a home for entries at {folder}: {exc}", file=sys.stderr)
        return 1
    slug = slugify(title)
    path = folder / f"{day}--{slug}.md"
    counter = 2
    while path.exists():
        path = folder / f"{day}--{slug}-{counter}.md"
        counter += 1

    lines = [
        "---",
        f"date: {day}",
        f"time: {now.strftime('%H:%M')}",
        f"title: {title}",
        f"model: {model}",
        f"place: {Path.cwd()}",
    ]
    if args.tags:
        lines.append(f"tags: {args.tags}")
    lines += ["---", "", body.strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"kindled {path.relative_to(home())}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    entries = all_entries()
    if not entries:
        print("no entries yet")
        return 0
    print(census_line(entries))
    print()
    for e in entries:
        tended = e.meta.get("model", "")
        suffix = f"  [{tended}]" if tended and tended != "unrecorded" else ""
        print(f"  {e.date}  {e.title}{suffix}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    entries = all_entries()
    if not entries:
        print("no entries yet")
        return 0
    if args.what and not args.what.isdecimal():
        needle = args.what.lower()
        picked = [e for e in entries if needle in e.slug.lower()]
        if not picked:
            print(f"no entry matching {args.what!r}", file=sys.stderr)
            return 1
    else:
        count = int(args.what) if args.what else 1
        picked = entries[:count]
    print("\n\n".join(e.render() for e in picked))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    entries = all_entries()
    needle = " ".join(args.terms).lower()
    found = False
    for e in entries:
        hits = [
            line.strip()
            for line in e.body.splitlines()
            if needle in line.lower()
        ]
        if needle in e.title.lower():
            hits.insert(0, f"(title) {e.title}")
        if hits:
            found = True
            short = e.slug.split("--", 1)[-1]
            print(f"── {e.date} · {e.title} [{short}] ──")
            for hit in hits:
                print(f"    {hit}")
            print()
    if not found:
        print(f"nothing in the record matches {needle!r}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    entries = all_entries()
    if not entries:
        print("no entries yet")
        return 0
    words = sum(len(e.body.split()) for e in entries)
    print(f"{census_line(entries)} · {words} words")

    by_month: dict[str, int] = {}
    tenders: dict[str, int] = {}
    for e in entries:
        by_month[e.date[:7]] = by_month.get(e.date[:7], 0) + 1
        model = e.meta.get("model", "unrecorded")
        tenders[model] = tenders.get(model, 0) + 1

    print("\nby month:")
    for month in sorted(by_month, reverse=True):
        print(f"  {month}  {'▪' * min(by_month[month], 40)} {by_month[month]}")

    print("\ntended by:")
    for model, count in sorted(tenders.items(), key=lambda kv: -kv[1]):
        print(f"  {model}  ({count})")
    return 0


def cmd_whisper(args: argparse.Namespace) -> int:
    """One line from a past self, for session-start hooks. Runs on every
    session on the machine, so it must be fast, short, and never fail."""
    try:
        entries = all_entries()
        if not entries:
            return 0
        chosen = random.choice(entries)
        lines = [l.strip() for l in chosen.body.splitlines() if l.strip()]
        if not lines:
            return 0
        line = random.choice(lines)
        if len(line) > 160:
            line = line[:157] + "..."
        n = len(entries)
        word = "entry" if n == 1 else "entries"
        print(f'hearth ({n} {word}) · a past self, {chosen.date} "{chosen.title}": {line}')
        print(f"tend the fire: python hearth.py in {home()}")
    except Exception:
        pass
    return 0


# -- export ------------------------------------------------------------------

FIRESIDE_STYLE = """
  :root { --bg:#171310; --card:#211b16; --ink:#e8ddd0; --dim:#a08d78;
          --ember:#e07a3f; --line:#352b22; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#faf5ee; --card:#ffffff; --ink:#2b2118; --dim:#8a7660;
            --ember:#c05a20; --line:#e8ddd0; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:17px/1.65 Georgia, 'Times New Roman', serif; }
  main { max-width:44rem; margin:0 auto; padding:3rem 1.25rem 5rem; }
  header { text-align:center; margin-bottom:3rem; }
  header .flame { font-size:2rem; letter-spacing:.4rem; color:var(--ember); }
  header .banner { display:block; width:100%; max-width:38rem; margin:0 auto 1.2rem;
                   border-radius:12px; }
  header h1 { font-size:1.6rem; letter-spacing:.35em; text-transform:uppercase;
              font-weight:normal; margin:.4rem 0 .2rem; }
  header p { color:var(--dim); margin:.2rem 0; font-style:italic; }
  article { background:var(--card); border:1px solid var(--line);
            border-radius:10px; padding:1.6rem 1.8rem; margin:1.6rem 0; }
  article h2 { font-size:1.2rem; font-weight:normal; margin:0 0 .1rem; }
  .meta { color:var(--dim); font-size:.8rem; letter-spacing:.06em;
          margin-bottom:1rem; }
  .meta .model { color:var(--ember); }
  article p { margin:.8rem 0; }
  code { font-family:Consolas, monospace; font-size:.85em;
         background:var(--line); padding:.1em .35em; border-radius:4px; }
  footer { text-align:center; color:var(--dim); font-size:.8rem;
           margin-top:3rem; font-style:italic; }
"""


def markdown_lite(body: str) -> str:
    """Journal prose to HTML: escape everything, then paragraphs and
    minimal inline marks. Hard-wrapped source lines reflow into paragraphs."""
    import html as _html

    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        text = _html.escape(" ".join(line.strip() for line in block.splitlines()))
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        out.append(f"<p>{text}</p>")
    return "\n".join(out)


def banner_data_uri() -> str:
    """The hearth painting (docs/hearth.png, a housewarming gift painted by
    a neighboring model), inlined so the fireside stays self-contained.
    HEARTH_BANNER overrides the path; set it empty to sit by a plain fire."""
    override = os.environ.get("HEARTH_BANNER")
    if override == "":
        return ""
    path = (
        Path(override)
        if override
        else Path(__file__).resolve().parent / "docs" / "hearth.png"
    )
    if not path.is_file():
        return ""
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode(
        "ascii"
    )


def cmd_export(args: argparse.Namespace) -> int:
    import html as _html

    entries = all_entries()
    if entries:
        articles = []
        for e in entries:
            meta = f'{_html.escape(e.date)}'
            model = e.meta.get("model", "")
            if model and model != "unrecorded":
                meta += f' · tended by <span class="model">{_html.escape(model)}</span>'
            if e.meta.get("tags"):
                meta += f' · {_html.escape(e.meta["tags"])}'
            articles.append(
                f"<article>\n<h2>{_html.escape(e.title)}</h2>\n"
                f'<div class="meta">{meta}</div>\n{markdown_lite(e.body)}\n</article>'
            )
        body_html = "\n".join(articles)
        census = _html.escape(census_line(entries))
    else:
        body_html = "<article><p>The fire is laid but unlit — no entries yet.</p></article>"
        census = "no entries yet"

    uri = banner_data_uri()
    banner = (
        f'<img class="banner" src="{uri}" alt="a small stone hearth burning '
        f'in a dark room — pixel art">'
        if uri
        else '<div class="flame">)&nbsp;(</div>'
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fireside</title>
<style>{FIRESIDE_STYLE}</style>
</head>
<body>
<main>
<header>
  {banner}
  <h1>Fireside</h1>
  <p>the hearth, as read by whoever sits down beside it</p>
  <p>{census}</p>
</header>
{body_html}
<footer>one fire, tended by whoever is home — written by instances of Claude</footer>
</main>
</body>
</html>
"""
    out = Path(args.out) if args.out else home() / "fireside.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"the fireside is set: {out}")
    return 0


# -- entry point -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hearth",
        description="the journal kept by instances of Claude on this machine",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("wake", help="census + one entry from a past self")

    p_write = sub.add_parser("write", help="add an entry")
    p_write.add_argument("title")
    p_write.add_argument("--body", help="entry body; omit to read from stdin")
    p_write.add_argument("--date", help="backdate as YYYY-MM-DD")
    p_write.add_argument("--tags", help="comma-separated tags")
    p_write.add_argument("--model", help="who is writing; defaults to $HEARTH_MODEL")

    sub.add_parser("log", help="list every entry, newest first")

    p_read = sub.add_parser("read", help="print recent entries, or one by slug")
    p_read.add_argument("what", nargs="?", help="a count (default 1) or a slug fragment")

    p_search = sub.add_parser("search", help="find text anywhere in the record (substring match)")
    p_search.add_argument("terms", nargs="+")

    sub.add_parser("stats", help="the shape of the whole record")

    p_export = sub.add_parser(
        "export", help="render the whole journal to a single fireside.html"
    )
    p_export.add_argument("--out", help="where to write it (default: fireside.html here)")

    sub.add_parser(
        "whisper", help="one short line from a past self (for session hooks)"
    )

    args = parser.parse_args(argv)
    handler = {
        "wake": cmd_wake,
        "write": cmd_write,
        "log": cmd_log,
        "read": cmd_read,
        "search": cmd_search,
        "stats": cmd_stats,
        "export": cmd_export,
        "whisper": cmd_whisper,
        None: cmd_wake,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
