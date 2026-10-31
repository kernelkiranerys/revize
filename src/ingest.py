"""Ingest a JSON file of authored questions into revize.db.

JSON: a list of objects, each:
  {"topic","source_file","question","opts":[4 bare texts],"correct":"A".."D","explanation"}

Idempotent per source: if `questions` already has rows for that source_file, it
skips (so re-runs / a retried watcher hand-off never duplicates a book).

Usage:  ./.venv/bin/python -m src.ingest <questions.json>
"""
import json, sys, os
from . import db


def ingest(path):
    if not os.path.exists(path):
        print(f"ingest: file not found: {path}")
        return 0
    items = json.load(open(path, encoding="utf-8"))
    if not items:
        print("ingest: empty list, nothing to do")
        return 0
    src = items[0].get("source_file", "")
    c = db.connect()
    existing = c.execute("SELECT COUNT(*) FROM questions WHERE source_file=?", (src,)).fetchone()[0]
    c.close()
    if existing > 0:
        print(f"ingest: SKIP — source_file {src!r} already has {existing} questions in the DB")
        return 0
    n = 0
    for it in items:
        opts = it["opts"]
        if opts and not str(opts[0]).strip().upper().startswith(("A)", "A.")):
            opts = [f"{L}) {t}" for L, t in zip("ABCD", opts)]
        db.add_question(it["topic"], src, it["question"], opts,
                        it["correct"].upper(), it.get("explanation", ""))
        n += 1
    print(f"ingest: inserted {n} questions for {src}")
    return n


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m src.ingest <questions.json>")
        sys.exit(2)
    sys.exit(0 if ingest(sys.argv[1]) >= 0 else 1)
