"""Inject AI-produced content into index.html between AUTO markers.

Contract (JSON produced by the judge step):
{
  "has_news": bool,
  "week_new_count": int | null,          # replaces the KPI number when present
  "digest_items": ["<li>...</li>", ...], # full curated weekly digest, newest first
  "changelog_entry": "<li>...</li>",     # one entry, prepended to the changelog
  "new_trials": ["<tr>...</tr>", ...],   # appended to the trial radar
  "new_papers": ["<li>...</li>", ...]    # appended to the literature radar
}
Every field except has_news is optional.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"


def replace_between(html, name, inner):
    start, end = f"<!--AUTO:{name}:start-->", f"<!--AUTO:{name}:end-->"
    i, j = html.find(start), html.find(end)
    if i == -1 or j == -1:
        return html
    return html[: i + len(start)] + inner + html[j:]


def prepend_after_start(html, name, snippet):
    start = f"<!--AUTO:{name}:start-->"
    i = html.find(start)
    if i == -1:
        return html
    at = i + len(start)
    return html[:at] + "\n      " + snippet + html[at:]


def insert_before_append(html, name, snippets):
    marker = f"<!--AUTO:{name}:append-->"
    i = html.find(marker)
    if i == -1 or not snippets:
        return html
    block = "".join("\n      " + s for s in snippets)
    return html[:i] + block + "\n      " + html[i:]


def apply(out, today, nxt):
    html = INDEX.read_text(encoding="utf-8")

    scan = f"最後掃描：<b>{today}</b>（今日）<br>下次掃描：<b>{nxt}</b>"
    html = replace_between(html, "scandate", scan)

    if out.get("week_new_count") is not None:
        html = replace_between(html, "weekcount", str(out["week_new_count"]))

    digest = out.get("digest_items") or []
    if digest:
        inner = "\n        " + "\n        ".join(digest) + "\n      "
        html = replace_between(html, "digest", inner)

    if out.get("new_trials"):
        html = insert_before_append(html, "trials", out["new_trials"])
    if out.get("new_papers"):
        html = insert_before_append(html, "papers", out["new_papers"])

    entry = out.get("changelog_entry")
    if entry:
        html = prepend_after_start(html, "changelog", entry)

    INDEX.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    today = sys.argv[2]
    nxt = sys.argv[3]
    apply(payload, today, nxt)
    print("index.html updated")
