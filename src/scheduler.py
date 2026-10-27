import datetime
from . import config, db

def _next_due(interval):
    return (datetime.date.today() + datetime.timedelta(days=interval)).isoformat()

def update(qid, quality):
    """SM-2 update. quality in 0..5 (we use 5=correct, 2=wrong)."""
    st = db.get_sr(qid)
    if st is None:
        ease, interval, reps = config.SM2_EASE0, 0, 0
    else:
        ease, interval, reps = st["ease"], st["interval_days"], st["reps"]

    if quality >= 3:                              # correct
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ease))
        reps += 1
    else:                                         # wrong - reset
        reps = 0
        interval = 1

    # SM-2 ease-factor update
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(config.SM2_EASE_MIN, ease)

    db.put_sr(qid, ease, interval, reps, _next_due(interval))
    return {"ease": ease, "interval_days": interval, "reps": reps,
            "due": _next_due(interval)}

def record(qid, given, correct, latency_s, session_id, quality=None):
    """Log a review + run SM-2. quality defaults from correctness."""
    db.log_review(qid, given, correct, latency_s, session_id)
    if quality is None:
        quality = config.QUAL_CORRECT if correct else config.QUAL_WRONG
    return update(qid, quality)

if __name__ == "__main__":
    # smoke test on qid 1
    print(update(1, config.QUAL_CORRECT))
