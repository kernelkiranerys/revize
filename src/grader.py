"""Parse and grade the user's SimpleX reply."""
import re
from . import config, db, scheduler
import time

_LETTER = re.compile(r"\b([A-Da-d])\b")
_NUM = {"1": "A", "2": "B", "3": "C", "4": "D"}

def parse_answer(text):
    """Return 'A'..'D' if the reply is a clear single answer, else None."""
    t = text.strip().lower()
    if not t:
        return None
    # exact single letter / number
    first = t.split()[0] if t.split() else t
    first = re.sub(r"[^a-z0-9]", "", first)
    if first in ("a", "b", "c", "d"):
        return first.upper()
    if first in _NUM:
        return _NUM[first]
    # 'answer: b' style
    m = _LETTER.search(t)
    return m.group(1).upper() if m else None

def is_command(text):
    t = text.strip().lower()
    if t in ("stop", "skip", "teach", "explain", "quiz", "go", "next", "help", "stats"):
        return t
    return None

def grade(qid, given_letter, session_id, t_started):
    q = db.get_question(qid)
    correct = (given_letter == q["correct"]) if given_letter else False
    latency = time.time() - t_started
    res = scheduler.record(qid, given_letter.upper() if given_letter else "",
                           correct, latency, session_id)
    return q, correct, res

def option_lines(q):
    return [q["opt_a"], q["opt_b"], q["opt_c"], q["opt_d"]]
