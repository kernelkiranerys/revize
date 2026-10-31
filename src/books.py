"""List ingested books: source_file, chunk count, question count, topic(s).

Run:  ./.venv/bin/python -m src.books
"""
from . import db


def books():
    c = db.connect()
    rows = c.execute("""
        SELECT ch.source_file AS src,
               (SELECT COUNT(*) FROM chunks  WHERE source_file = ch.source_file) AS chunks,
               (SELECT COUNT(*) FROM questions WHERE source_file = ch.source_file) AS qs,
               (SELECT GROUP_CONCAT(DISTINCT topic) FROM questions WHERE source_file = ch.source_file) AS topic
        FROM chunks ch
        GROUP BY ch.source_file
        ORDER BY ch.source_file
    """).fetchall()
    c.close()
    print(f"{'source_file':68} {'chunks':>6} {'Qs':>4}  topic")
    print("-" * 110)
    for r in rows:
        print(f"{r['src'][:68]:68} {r['chunks']:>6} {r['qs']:>4}  {r['topic'] or '-'}")
    print("-" * 110)
    tot_c = sum(r["chunks"] for r in rows)
    tot_q = sum(r["qs"] for r in rows)
    print(f"{len(rows)} books  ·  {tot_c} chunks  ·  {tot_q} questions")


if __name__ == "__main__":
    books()
