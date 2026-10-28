"""RAG tutor: retrieve chunks (sqlite-vec) + call Ollama with sandboxed prompts.

Two surfaces:
  explain(qid, given)            — one-shot rationale for a quiz question.
  start_lesson / continue_lesson  — CONVERSATIONAL teach mode: the bot holds a
                                    message history; each follow-up re-retrieves
                                    (scoped to the topic's books) and the LLM
                                    keeps the thread, so the user can drill down.
"""
import os, json, re, urllib.request
from . import config, db, chunker, grader

PROMPT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")

def _load(name):
    with open(os.path.join(PROMPT_DIR, name), encoding="utf-8") as f:
        return f.read()

def _strip_md(s):
    """Scrubb markdown so it renders cleanly as plain text on SimpleX."""
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)          # **bold**
    s = re.sub(r"__([^_]+)__", r"\1", s)               # __bold__
    s = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", s)  # *italic*
    s = re.sub(r"`([^`]+)`", r"\1", s)                 # `code`
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)       # headings
    s = re.sub(r"^\s*[-*]\s+", "• ", s, flags=re.M)    # - bullet -> •
    return s

def retrieve(query_text, source_file=None, source_files=None, k=None):
    try:
        qv = chunker.embed(query_text)
    except Exception as e:
        return [], f"embed failed: {e}"
    return db.search_chunks(qv, k=k, source_file=source_file, source_files=source_files), None

def _ctx_block(chunks):
    return "\n---\n".join(
        f"[{c['source_file']} / {c['heading']}] {c['text'][:600]}" for c in chunks) or "(no chunks found)"

def _chat(messages, max_tokens):
    payload = json.dumps({
        "model": config.CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3},
    }).encode()
    req = urllib.request.Request(config.OLLAMA_HOST.rstrip("/") + "/api/chat",
                                 data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return _strip_md(json.load(r)["message"]["content"].strip())

# ── one-shot: explain a quiz question's answer ──────────────────────────
def explain(qid, given_letter):
    q = db.get_question(qid)
    chunks, err = retrieve(f"{q['question']} {q['explanation']}", source_file=q["source_file"])
    if err:
        return f"[tutor offline: {err}]"
    options = "\n".join(grader.option_lines(q))
    prompt = (_load("explain.txt")
              .replace("{CHUNKS}", _ctx_block(chunks))
              .replace("{QUESTION}", q["question"])
              .replace("{OPTIONS}", options)
              .replace("{CORRECT}", q["correct"])
              .replace("{GIVEN}", given_letter or "(no answer)")
              .replace("{VERDICT}", "correct" if given_letter == q["correct"] else "wrong"))
    return _chat([{"role": "system", "content": prompt}], config.EXPLAIN_MAX_TOKENS)

# ── conversational teach mode ───────────────────────────────────────────
_TEACH_SYS = None
def _teach_system():
    global _TEACH_SYS
    if _TEACH_SYS is None:
        _TEACH_SYS = _load("teach_chat.txt")
    return _TEACH_SYS

def _trim(history, keep=12):
    """Keep the system message + the last `keep` turns (avoid unbounded growth)."""
    if len(history) <= keep + 1:
        return history
    return [history[0]] + history[-(keep):]

def start_lesson(subject, scope_files=None):
    """Open a teach conversation on `subject`, scoped to `scope_files` books.
    Returns (reply, messages) where messages is the transcript to continue."""
    chunks, err = retrieve(subject, source_files=scope_files)
    if err:
        return f"[tutor offline: {err}]", []
    messages = [
        {"role": "system", "content": _teach_system()},
        {"role": "user", "content": f"[Context]\n{_ctx_block(chunks)}\n\nExplain, for a beginner-to-intermediate learner: {subject}"},
    ]
    reply = _chat(messages, config.TEACH_MAX_TOKENS)
    messages.append({"role": "assistant", "content": reply})
    return reply, _trim(messages)

def continue_lesson(history, followup, scope_files=None):
    """Continue a teach conversation: re-retrieve for the follow-up (scoped),
    inject context, keep the thread. Returns (reply, updated_history)."""
    if not history:
        return start_lesson(followup, scope_files)
    chunks, err = retrieve(followup, source_files=scope_files)
    if err:
        return f"[tutor offline: {err}]", history
    history = _trim(history + [{"role": "user",
        "content": f"[Context]\n{_ctx_block(chunks)}\n\nFollow-up: {followup}\n(Stay on topic; go deeper using the context; if it isn't in the context, say so.)"}])
    reply = _chat(history, config.TEACH_MAX_TOKENS)
    history.append({"role": "assistant", "content": reply})
    return reply, _trim(history)
