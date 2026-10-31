"""revize book-watcher (recursive, folder-as-topic).

Watches ./inbox recursively. The folder a book is dropped in IS
its topic:
  revize-inbox/<Topic>/<book>          → topic=<Topic>, BOOK_QCOUNT questions (50)
  revize-inbox/uni/<module>/<book>     → topic=<module>, the exception:
        * module handbook (filename contains 'handbook') → chunked for querying
          but 0 questions (query-only; teachable, never quizzed)
        * other docs (lesson material)                   → UNI_LESSON_QCOUNT (12)

Each settled file is handed to ai-agent (convert → chunk+embed → author N →
insert); the book is registered in the `books` table with its folder topic so a
teach session scoped to that topic retrieves from it (the handbook included).
Processed files STAY in their folder (state prevents re-processing — no move).
A confirmation is written to the ai-agent bridge outbox so your phone gets a text.

Run:  ./.venv/bin/python -m src.watcher
"""
import os, time, json, subprocess, shutil, traceback
from . import config, db

WATCH_DIR = config.WATCH_DIR
STATE_DIR = os.path.expanduser("~/.revize-watcher")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
OUTBOX = os.path.expanduser("~/.simplex-bridge/outbox")
DIRECTIVE_FILE = os.path.join(os.path.dirname(__file__), "..", "prompts", "ingest_directive.txt")
# CLI of the LLM coding agent used for end-to-end ingestion. Override via
# env var to plug in opencode, Claude Code, Cursor, etc. Default assumes
# `ai-agent` is on PATH.
AI_AGENT = os.environ.get("AI_AGENT_CMD", shutil.which("ai-agent") or "/usr/local/bin/ai-agent")
SETTLE_SECONDS = 15
POLL_INTERVAL = 10
AI_AGENT_TIMEOUT = 3600
SKIP_DIRS = {"done"}


def _log(msg):
    line = f"[{time.strftime('%F %T')}] {msg}"
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(os.path.join(STATE_DIR, "watcher.log"), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(f"[watcher] {msg}", flush=True)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            pass
    return {}


def save_state(s):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def notify(msg):
    os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
    with open(OUTBOX, "a") as f:
        f.write(msg.strip()[:3900] + "\n")
    _log(f"notified phone: {msg[:80]!r}")


def extract_text(raw):
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "text":
            t = ev.get("part", {}).get("text", "")
            if t:
                out.append(t)
    return " ".join(out)


def _source_file(path):
    stem = os.path.basename(path)
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem + ".md"


def _plan(path):
    """Return (topic, qcount, is_handbook) for a file, or None to skip."""
    rel = os.path.relpath(path, WATCH_DIR)
    parts = rel.split(os.sep)
    if parts[0] in SKIP_DIRS:
        return None
    is_handbook = "handbook" in os.path.basename(path).lower()
    if parts[0] == "uni":
        if len(parts) < 3:                      # uni/ itself or uni/<module>/ (a dir)
            return None
        return (parts[1], 0 if is_handbook else config.UNI_LESSON_QCOUNT, is_handbook)
    return (parts[0], 0 if is_handbook else config.BOOK_QCOUNT, is_handbook)


def _build_directive(path, topic, qcount, is_handbook):
    tmpl = open(DIRECTIVE_FILE, encoding="utf-8").read()
    if is_handbook:
        note = ("This file is a module HANDBOOK (query-only). Do NOT author any quiz "
                "questions from it — only convert (step 1) and chunk+embed (step 2). "
                "Skip steps 3-4. It will be queryable via 'teach " + topic + "' but never quizzed.")
        author = ("3. (handbook — no questions authored.)\n"
                  "4. (skipped — handbook is query-only.)")
    else:
        note = ""
        n = qcount
        author = (
            f"3. AUTHOR EXACTLY {n} MCQs: read the converted .md, mine ~{n+10} discrete "
            f"verbatim question-worthy facts (definitions, numbers/ports, command flags, "
            f"classifications, process orders), then write EXACTLY {n} beginner-to-intermediate "
            f"multiple-choice questions, diversified across the book, each with ONE clear "
            f"correct answer and 3 plausible distractors. Vary the type: identification / "
            f"numeric / process-order / 'which of the following'. Every answer and explanation "
            f"must be grounded in the actual text — do NOT invent facts. Format each as a JSON "
            f'object: {{"topic": "{topic}", "source_file": "<the .md basename>", "question": ..., '
            f'"opts": [<4 bare option texts, no "A) " prefix>], "correct": "A".."D", '
            f'"explanation": <one line, grounded>}}. Write the array of {n} objects to '
            f"/tmp/revize_ingest_<stem>.json (stem = the .md basename without extension).\n"
            f"4. INSERT: ./.venv/bin/python -m src.ingest /tmp/revize_ingest_<stem>.json "
            f"(idempotent — skips if that source_file already has questions). It prints how many it inserted."
        )
    return (tmpl.replace("{PATH}", path).replace("{TOPIC}", topic)
            .replace("{HANDBOOK_NOTE}", note).replace("{AUTHOR_BLOCK}", author))


def hand_off(path, plan):
    topic, qcount, is_handbook = plan
    _log(f"hand off: {os.path.relpath(path, WATCH_DIR)}  (topic={topic}, qcount={qcount}, handbook={is_handbook})")
    directive = _build_directive(path, topic, qcount, is_handbook)
    cmd = [AI_AGENT, "run", directive, "--dir", "~",
           "--dangerously-skip-permissions", "--format", "json"]
    _log(f"spawn ai-agent (directive {len(directive)} chars, timeout {AI_AGENT_TIMEOUT}s)")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=AI_AGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, f"ai-agent timeout after {AI_AGENT_TIMEOUT}s"
    except Exception as e:
        return None, f"ai-agent spawn error: {e}"
    reply = extract_text(r.stdout) or ""
    if r.returncode != 0 and not reply:
        return None, f"ai-agent rc={r.returncode} stderr={r.stderr[:300]}"
    # register the book with its folder-topic so teach-scope includes it (handbook too)
    try:
        db.set_book(_source_file(path), topic, path)
    except Exception as e:
        _log(f"set_book failed for {_source_file(path)}: {e}")
    return reply, None


def _verify(source_file):
    c = db.connect()
    chunks = c.execute("SELECT COUNT(*) FROM chunks WHERE source_file=?", (source_file,)).fetchone()[0]
    questions = c.execute("SELECT COUNT(*) FROM questions WHERE source_file=?", (source_file,)).fetchone()[0]
    topics = [r[0] for r in c.execute("SELECT DISTINCT topic FROM questions WHERE source_file=?", (source_file,))]
    c.close()
    return chunks, questions, topics


def main():
    os.makedirs(WATCH_DIR, exist_ok=True)
    _log(f"watching {WATCH_DIR} recursively (poll={POLL_INTERVAL}s, settle={SETTLE_SECONDS}s)")
    state = load_state()
    sizes = {}
    while True:
        try:
            for root, dirs, files in os.walk(WATCH_DIR):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for fn in files:
                    path = os.path.join(root, fn)
                    plan = _plan(path)
                    if plan is None:
                        continue
                    key = path
                    if state.get(key, {}).get("status") in ("done", "processing", "failed"):
                        continue
                    try:
                        sz = os.path.getsize(path)
                    except OSError:
                        continue
                    rec = sizes.get(key)
                    if rec is None or rec[0] != sz:
                        sizes[key] = (sz, time.time())
                        continue
                    if time.time() - rec[1] < SETTLE_SECONDS:
                        continue
                    state[key] = {"status": "processing", "path": path,
                                  "topic": plan[0], "started": time.strftime("%F %T")}
                    save_state(state)
                    sizes.pop(key, None)
                    reply, err = hand_off(path, plan)
                    sf = _source_file(path)
                    chunks, questions, topics = _verify(sf)
                    topic, qcount, is_hb = plan
                    if err:
                        summary = f"ai-agent error: {err}"
                    elif is_hb:
                        summary = f"{sf}: {chunks} chunks, query-only handbook (0 questions), topic: {topic}"
                    elif questions == 0:
                        err = "ai-agent finished but 0 questions in DB"
                        summary = err
                    else:
                        summary = f"{sf}: {chunks} chunks, {questions} questions, topic: {topic}"
                    if err:
                        state[key]["status"] = "failed"
                        state[key]["error"] = summary
                        state[key]["reply"] = (reply or "")[:500]
                        _log(f"FAILED {fn}: {summary}")
                        notify(f"revize ingest FAILED — {fn}: {summary}")
                    else:
                        state[key]["status"] = "done"
                        state[key]["summary"] = summary
                        state[key]["reply"] = (reply or "")[:500]
                        _log(f"DONE {fn}: {summary}")
                        notify(f"revize ingest done — {summary}")
                    state[key]["finished"] = time.strftime("%F %T")
                    save_state(state)
        except Exception as e:
            _log(f"uncaught: {e}\n{traceback.format_exc()}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
