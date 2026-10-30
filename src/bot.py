"""revize bot — morning kickoff + reactive ping-pong over SimpleX.

Run daemon:   ./.venv/bin/python -m src.bot
Force kickoff: ... -m src.bot kickoff     (also starts daemon if not running)

SimpleX commands (see USER_GUIDE.md for full detail):
  a/b/c/d | 1-4            answer the current question
  quiz | go | next         start/resume a mixed SM-2 session (all topics)
  quiz <topic>             session filtered to one topic (e.g. 'quiz opnsense')
  quiz new                 session of fresh cards only (never reviewed)
  quiz hard                session of your weak spots (≥1 wrong review)
  teach                    RAG lesson on the current question
  teach <topic>            free-form RAG lesson on a topic
  skip                     skip current (counts wrong), next
  stop                     pause session
  stats                    overall accuracy + due counts
  stats <topic>            per-topic stats
  topics                   list all topics with question counts
  help                     command list
"""
import os, sys, time, datetime, signal
from . import config, db, grader, scheduler, tutor, simplex_io


class Bot:
    def __init__(self):
        db.init_db()
        self.sx = simplex_io.QuizBot()
        self.current_qid = None
        self.q_started_at = None
        self.session_id = f"s-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        self.asked = set()                 # qids asked this session
        self.filter = (None, None)         # (topic, mode) active for the session
        self.teach_active = False          # conversational teach mode
        self.teach_history = []            # [{role,content}] transcript
        self.teach_scope = None            # list of source_files to retrieve within, or None
        self.count_answered = 0
        self.last_kickoff_date = None      # ISO date string
        self.running = True

    # ── message formatting ──────────────────────────────────────────────
    def _fmt_question(self, q):
        lines = [f"Q{q['id']} ({q['topic']})", q["question"],
                 q["opt_a"], q["opt_b"], q["opt_c"], q["opt_d"],
                 "Reply a/b/c/d · 'teach' for a lesson · 'skip' · 'stop'"]
        return "\n".join(lines)

    def _help(self):
        return ("a/b/c/d answer · quiz [mixed|<topic>|new|hard] · teach [topic] (drill down, then 'done') · "
                "skip · stop · stats [topic] · topics · help")

    def _filter_label(self, topic=None, mode=None):
        t, m = (topic, mode) if (topic or mode) else self.filter
        if m == "new":  return "fresh cards"
        if m == "hard": return "weak spots"
        if t:           return f"topic: {t}"
        return "all topics (SM-2)"

    def _parse_quiz_arg(self, rest):
        r = (rest or "").strip().lower()
        if r in ("new",):           return (None, "new")
        if r in ("hard", "weak"):   return (None, "hard")
        if r:                       return (r, None)
        return (None, None)

    # ── info commands ───────────────────────────────────────────────────
    def _topics(self):
        c = db.connect()
        rows = c.execute("SELECT topic, COUNT(*) n FROM questions GROUP BY topic ORDER BY n DESC").fetchall()
        c.close()
        if not rows:
            return "No topics yet."
        return "Topics: " + " · ".join(f"{r['topic']} ({r['n']})" for r in rows)

    def _stats(self, topic=None):
        today = datetime.date.today().isoformat()
        c = db.connect()
        if topic:
            lp = f"%{topic.lower()}%"
            tot = c.execute("SELECT COUNT(*) FROM questions WHERE LOWER(topic) LIKE ?", (lp,)).fetchone()[0]
            rev = c.execute("SELECT COUNT(*) FROM reviews r JOIN questions q ON q.id=r.qid WHERE LOWER(q.topic) LIKE ?", (lp,)).fetchone()[0]
            cor = c.execute("SELECT COUNT(*) FROM reviews r JOIN questions q ON q.id=r.qid WHERE LOWER(q.topic) LIKE ? AND r.correct=1", (lp,)).fetchone()[0]
            due = c.execute("SELECT COUNT(*) FROM sr_state s JOIN questions q ON q.id=s.qid WHERE LOWER(q.topic) LIKE ? AND s.due<=?", (lp, today)).fetchone()[0]
            c.close()
            rate = f"{100*cor//rev}%" if rev else "n/a"
            return f"{topic}: {tot} questions, {rev} reviews ({rate} correct), {due} due today."
        tot = c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        rev = c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        cor = c.execute("SELECT COUNT(*) FROM reviews WHERE correct=1").fetchone()[0]
        due = c.execute("SELECT COUNT(*) FROM sr_state WHERE due<=?", (today,)).fetchone()[0]
        c.close()
        rate = f"{100*cor//rev}%" if rev else "n/a"
        return (f"Stats: {rev} reviews ({rate} correct) across {tot} questions, {due} due today. "
                f"Session {self.session_id}: {self.count_answered} answered. Filter: {self._filter_label()}.")

    # ── question selection ─────────────────────────────────────────────
    def pick_question(self, topic=None, mode=None):
        t = topic if topic is not None else self.filter[0]
        m = mode if mode is not None else self.filter[1]
        due = db.get_due_qids(limit=10, exclude=tuple(self.asked), topic=t, mode=m)
        if due:
            return due[0]
        # default mode only: if nothing is due, fall back to a random not-yet-asked
        if not t and not m:
            c = db.connect()
            if self.asked:
                ph = ",".join("?" * len(self.asked))
                rows = c.execute(f"SELECT id FROM questions WHERE id NOT IN ({ph}) ORDER BY RANDOM() LIMIT 1",
                                 tuple(self.asked)).fetchall()
            else:
                rows = c.execute("SELECT id FROM questions ORDER BY RANDOM() LIMIT 1").fetchall()
            c.close()
            return rows[0]["id"] if rows else None
        return None

    def send_question(self, qid=None):
        if qid is None:
            qid = self.pick_question()
        if qid is None:
            self.sx.send(f"No questions match '{self._filter_label()}'. Try 'quiz' (all), 'topics', or 'quiz new'.")
            return False
        q = db.get_question(qid)
        self.current_qid = qid
        self.q_started_at = time.time()
        self.asked.add(qid)
        return self.sx.send(self._fmt_question(q))

    # ── teach-mode helpers ──────────────────────────────────────────────
    def _enter_teach(self, rest):
        rest = (rest or "").strip()
        if not rest:
            if self.current_qid:
                q = db.get_question(self.current_qid)
                scope, subject = [q["source_file"]], f"{q['topic']}: {q['question']}"
            else:
                self.sx.send("Teach what? e.g. 'teach opnsense' or 'teach SYN scans'."); return
        else:
            scope = db.source_files_for_topic(rest) or None   # None = global for a free-form subject
            subject = rest
        self.teach_scope = scope
        reply, hist = tutor.start_lesson(subject, scope)
        self.teach_history = hist
        self.teach_active = bool(hist)
        if hist:
            self.sx.send(reply + "\n\nDrill down: type a follow-up (e.g. 'tell me about firewall rules', "
                        "'give an example', 'more depth'), or 'done' to return to the quiz.")
        else:
            self.sx.send(reply)

    def _exit_teach(self):
        self.teach_active = False
        self.teach_history = []
        self.teach_scope = None

    def _answer(self, ans):
        if self.current_qid is None:
            self.sx.send("No question pending — text 'quiz' to start one."); return
        q, correct, res = grader.grade(self.current_qid, ans, self.session_id, self.q_started_at)
        self.count_answered += 1
        self.current_qid = None
        if correct:
            fb = f"✓ Correct — {q['explanation']}"
        else:
            fb = f"✗ It's {q['correct']}. {q['explanation']}\nReply 'teach' for the full lesson, or answer the next:"
        if self.count_answered and self.count_answered % config.SOFT_NUDGE_AFTER == 0:
            fb += "\n(still going? reply to continue, or 'stop' to pause)"
        fb += "\n\n"
        self.sx.send(fb)
        self.send_question()

    # ── routing ─────────────────────────────────────────────────────────
    def handle(self, text):
        t = text.strip()
        parts = t.split(None, 1)
        head = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        # ── conversational teach mode: any non-command is a follow-up ──
        if self.teach_active:
            if head in ("done", "exit", "end"):
                self._exit_teach()
                self.sx.send("Back to quiz mode." + ("" if self.current_qid else " Text 'quiz' to start."))
                if self.current_qid:
                    self.sx.send(self._fmt_question(db.get_question(self.current_qid)))
                return
            if head == "stop":
                self._exit_teach(); self.current_qid = None; self.filter = (None, None)
                self.sx.send("Teach ended. Session paused. ☘"); return
            if head in ("quiz", "go", "next"):
                self._exit_teach()
                topic, mode = self._parse_quiz_arg(rest)
                self.filter = (topic, mode)
                self.sx.send("Here we go —"); self.send_question(); return
            if head == "help":
                self.sx.send(self._help() + "  (in teach mode: just type your follow-up, or 'done'.)"); return
            if head == "topics":
                self.sx.send(self._topics()); return
            if head == "stats":
                self.sx.send(self._stats(rest or None)); return
            ans = grader.parse_answer(text)
            if ans and self.current_qid:           # leave teach to answer the pending Q
                self._exit_teach(); self._answer(ans); return
            # otherwise: treat the whole message as a follow-up question
            reply, self.teach_history = tutor.continue_lesson(self.teach_history, text, self.teach_scope)
            self.sx.send(reply); return

        # ── normal (quiz) routing ──
        if head == "stop":
            self.current_qid = None; self.filter = (None, None)
            self.sx.send("Session paused. Text 'quiz' to resume. ☘"); return
        if head == "help":
            self.sx.send(self._help()); return
        if head == "topics":
            self.sx.send(self._topics()); return
        if head == "stats":
            self.sx.send(self._stats(rest or None)); return
        if head in ("teach", "explain"):
            self._enter_teach(rest); return
        if head == "skip":
            if self.current_qid:
                q, _, _ = grader.grade(self.current_qid, None, self.session_id, self.q_started_at or time.time())
                self.sx.send(f"Skipped — it's {q['correct']}. {q['explanation']}")
                self.current_qid = None
            self.send_question(); return
        if head in ("quiz", "go", "next"):
            topic, mode = self._parse_quiz_arg(rest)
            self.filter = (topic, mode)
            lbl = self._filter_label(topic, mode)
            self.sx.send(f"Starting — {lbl}." if lbl != "all topics (SM-2)" else "Here we go —")
            self.send_question(); return

        # otherwise: try to grade as an answer
        ans = grader.parse_answer(text)
        if ans is None:
            self.sx.send("Send a/b/c/d (or 'quiz'/'teach'/'skip'/'stop'/'stats'/'topics')."); return
        self._answer(ans)

    # ── daily kickoff ───────────────────────────────────────────────────
    def maybe_kickoff(self):
        now = datetime.datetime.now()
        today = now.date().isoformat()
        if self.last_kickoff_date == today:
            return
        if now.hour < config.KICKOFF_HOUR:
            return
        if self.teach_active:
            self.last_kickoff_date = today     # don't interrupt an open teach session
            return
        if self.current_qid is not None:
            self.last_kickoff_date = today     # a question is already pending, count it
            return
        self.last_kickoff_date = today
        self.session_id = f"s-{today}-{now:%H%M%S}"
        self.asked.clear()
        self.filter = (None, None)
        self.count_answered = 0
        self.sx.send("☀ Morning revision — here's your first question.")
        self.send_question()

    # ── main loop ───────────────────────────────────────────────────────
    def stop(self, *a):
        self.running = False

    def run(self, force_kickoff=False):
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        if not self.sx.start():
            print("FATAL: simplex-chat would not start"); sys.exit(1)
        for _ in range(3):
            if self.sx.resolve_contact():
                break
            time.sleep(2)
        if not self.sx.contact_id:
            print("NOTE: no contact yet. Run setup-quizbot.sh to create the profile + QR.")
        if force_kickoff:
            self.maybe_kickoff()
        self.last_kickoff_date = db.meta_get("last_kickoff_date")
        while self.running:
            try:
                if self.sx.proc and self.sx.proc.poll() is not None:
                    print("[bot] simplex-chat died, restarting"); self.sx.start()
                self.maybe_kickoff()
                for mid, text in self.sx.new_messages():
                    print(f"[bot] <- {text[:80]!r}")
                    self.handle(text)
                if self.last_kickoff_date:
                    db.meta_set("last_kickoff_date", self.last_kickoff_date)
            except Exception as e:
                print(f"[bot] uncaught: {e}\n{__import__('traceback').format_exc()}")
            time.sleep(config.POLL_INTERVAL)
        self.sx.stop()
        print("[bot] stopped")


def main():
    force = len(sys.argv) > 1 and sys.argv[1] == "kickoff"
    Bot().run(force_kickoff=force)

if __name__ == "__main__":
    main()
