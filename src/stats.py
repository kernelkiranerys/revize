"""Print revize.db stats: totals, per-topic breakdown, due counts.

Run:  ./.venv/bin/python -m src.stats
"""
import datetime
from . import db


def stats():
    today = datetime.date.today().isoformat()
    c = db.connect()
    q = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    rev = c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    cor = c.execute("SELECT COUNT(*) FROM reviews WHERE correct=1").fetchone()[0]
    due = c.execute("SELECT COUNT(*) FROM sr_state WHERE due<=?", (today,)).fetchone()[0]
    chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    books = c.execute("SELECT COUNT(DISTINCT source_file) FROM chunks").fetchone()[0]
    rate = f"{100 * cor // rev}%" if rev else "n/a"
    print("=== revize.db ===")
    print(f"books: {books}  chunks: {chunks}  questions: {q}  "
          f"reviews: {rev} ({rate} correct)  due today: {due}")
    print()
    print(f"  {'topic':24} {'Qs':>5} {'reviews':>8} {'correct':>8} {'due':>5}")
    print("  " + "-" * 60)
    for r in c.execute(
            """SELECT q.topic,
                  (SELECT COUNT(*) FROM questions WHERE topic=q.topic) AS qs,
                  (SELECT COUNT(*) FROM reviews r JOIN questions qq ON qq.id=r.qid WHERE qq.topic=q.topic) AS rv,
                  (SELECT COUNT(*) FROM reviews r JOIN questions qq ON qq.id=r.qid WHERE qq.topic=q.topic AND r.correct=1) AS co,
                  (SELECT COUNT(*) FROM sr_state s JOIN questions qq ON qq.id=s.qid WHERE qq.topic=q.topic AND s.due<=?) AS du
               FROM questions q GROUP BY topic ORDER BY qs DESC""", (today,)):
        print(f"  {r['topic']:24} {r['qs']:>5} {r['rv']:>8} {r['co']:>8} {r['du']:>5}")
    c.close()


if __name__ == "__main__":
    stats()
