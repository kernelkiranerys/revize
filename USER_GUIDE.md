# revize — User Guide

> How to **use** revize day-to-day: the SimpleX chat commands for training, and
> the shell commands to view/maintain the database and the book-ingestion
> pipeline. This is the operator's manual; for internals/architecture see
> `GUIDE.md`.

revize is your personal spaced-repetition revision bot. It lives on the NixOS
box as a background service and talks to you over **SimpleX Chat** on your
phone (a contact called **QuizBot**). Each morning it opens a conversation with
one multiple-choice question from your own cybersecurity/networking textbook
library, and keeps the conversation going — answer → grade → next question —
for as long as you keep replying. Get one wrong, or ask for a lesson, and a
local self-hosted model (Qwen2.5 7B) explains it, grounded in the actual
textbooks (no hallucinated facts).

You interact with revize in two ways:
1. **On your phone**, in the QuizBot SimpleX chat — answer questions, steer
   sessions, ask for lessons, check stats. (§2–§4)
2. **In a terminal on the box** — view/maintain the database and the
   book-ingestion pipeline. (§5–§7)

There is nothing to install or configure to use it day-to-day — it auto-starts
at boot and just runs.

---

## 1. The daily flow (what to expect on your phone)

- **~08:00 each day** the QuizBot sends one message: *☀ Morning revision —
  here's your first question.* followed by a multiple-choice question.
- **Reply with the letter** (`a`, `b`, `c`, or `d` — case-insensitive; `1-4`
  also works; even `c)` or `answer: b`). Within ~2 s it replies:
  - **✓ Correct** — one-line explanation, then the **next question**.
  - **✗ It's X** — one-line why, plus *Reply 'teach' for the full lesson, or
    answer the next:* — then the next question.
- **It keeps going as long as you reply.** There is no timeout — you can
  answer one, go make coffee, answer another; the session just waits. When
  you're done, text `stop` (or just stop replying).
- **Spacing:** questions you get right come back less often; ones you miss
  come back soon (SM-2 spaced repetition). Over time you see the hard ones
  more.
- After **25 answered** in one session it inserts a one-line *(still going?)*
  check — reply to continue, or `stop` to pause.
- You can start a session any time, not just 08:00: text `quiz`. Or target a
  topic/mode (§3–§4).

---

## 2. SimpleX commands (full reference)

Send any of these to the QuizBot contact on your phone. Commands are
case-insensitive; the first word is the command, the rest is its argument.

### Answering
| Send | Effect |
|---|---|
| `a` / `b` / `c` / `d` | Answer the current question (also `1`-`4`, `c)`, `answer: b`). Graded instantly → feedback → next question. |
| `skip` | Give up on the current question (recorded as wrong, rescheduled sooner) → next question. |

### Starting / steering a session
| Send | Effect |
|---|---|
| `quiz` (or `go` / `next`) | Start/resume a **mixed** session — all topics, SM-2 due-order. |
| `quiz <topic>` | Session filtered to one topic, e.g. `quiz opnsense`, `quiz pentesting`, `quiz "zero trust"`. (Case-insensitive, partial match.) |
| `quiz new` | Session of **fresh cards only** — questions you've never answered. |
| `quiz hard` | Session of your **weak spots** — questions you've gotten wrong at least once. |
| `stop` | Pause the session and reset the filter. Text `quiz` to resume. |

> The active **filter sticks** across your answers until you change it or text
> `stop`. So `quiz opnsense` keeps you on OPNsense question after question;
> `quiz` (no argument) returns to mixed. If a filtered session runs dry it says
> *"No questions match …"* — try `quiz` (all) or `topics`.

### Learning (conversational teach mode)
| Send | Effect |
|---|---|
| `teach <topic>` | Enter a teach conversation on a topic, scoped to its books — e.g. `teach opnsense`, `teach "zero trust"`, `teach SYN scans`, `teach CIA triad`. You get a grounded overview + a suggested next drill-down. |
| `teach` | With a question pending: enter a teach conversation scoped to that question's book (drill into the why / related concepts). |
| *(any follow-up)* | While in teach mode, anything you type that isn't a command is a follow-up — e.g. `tell me about firewall rules`, `give an example`, `more depth on aliases`. It re-retrieves within the topic's books and keeps the thread, so you can drill down. |
| `done` (or `quiz` / `stop`) | Leave teach mode and return to quizzing. |

`teach` uses RAG over your textbook chunks (scoped to the topic's books) and
keeps the conversation history so the thread stays coherent. It only states
what's in the books; if it's not in your notes it says so rather than inventing.
Output is stripped of markdown so it renders cleanly on the phone.

### Info
| Send | Effect |
|---|---|
| `stats` | Overall: total questions, reviews, accuracy %, due-today, session count, active filter. |
| `stats <topic>` | Per-topic version, e.g. `stats opnsense`. |
| `topics` | List every topic with its question count (e.g. `Zero Trust (50) · Beginner Networking (25) · …`). |
| `help` | Remind you of the commands. |

## 3. Getting different types of training

Pick the mode that matches what you want right now:

- **Daily mixed revision** — do nothing; the 08:00 question arrives, or text
  `quiz`. Spaced repetition surfaces what's due across all topics. Best for
  steady overall retention.
- **Focus a weak area** — `quiz hard` drills the questions you've previously
  gotten wrong (the ones with the lowest ease / a wrong review on record).
  Great the day before an exam topic.
- **Learn fresh material** — `quiz new` runs only never-reviewed cards. Use
  right after you ingest a new book so its 50 new questions get their first
  pass.
- **Topic-specific cram** — `quiz <topic>` (e.g. `quiz opnsense`). Combine
  with `stats <topic>` first to see how you're doing on it.
- **Just learn, no quiz** — `teach <topic>` gives a grounded mini-lesson from
  the textbooks when you want to understand rather than be tested.
- **Conversational deep-dive** — `teach <topic>` then keep typing follow-ups
  (`more depth`, `tell me about <subtopic>`, `give an example`). It stays on
  the topic, scoped to that topic's books, and remembers the thread — the way
  to actually drill into a concept rather than get a one-line overview. Text
  `done` to return to quizzing.
- **Targeted remediation** — when you miss a question, reply `teach` for a
  fuller explanation of *that* question (scoped to its book); keep drilling
  with follow-ups before answering the next.

## 4. Shell commands — view & maintain the database

Run these in a terminal on the box. The venv python is
`./.venv/bin/python`; run them from `.` so the
`src` package resolves (e.g. `cd . && .venv/bin/python -m …`).

### Inspect
| Command | Shows |
|---|---|
| `.venv/bin/python -m src.books` | Every ingested book: chunk count, question count, topic(s). |
| `.venv/bin/python -m src.stats` | Overall totals + per-topic table (questions, reviews, accuracy, due). |
| `cat ~/.revize-watcher/state.json` | Which books the watcher has processed, with status + summary. |

### Ad-hoc DB queries
For anything not covered, query `revize.db` directly via Python (sqlite3 is
built into the venv; `sqlite-vec` loads automatically via `db.connect()`):
```bash
cd . && .venv/bin/python -c "
from src import db
c = db.connect()
# example: your 10 worst questions (lowest ease)
for r in c.execute('SELECT q.id,q.topic,q.question,s.ease FROM sr_state s JOIN questions q ON q.id=s.qid ORDER BY s.ease LIMIT 10'):
    print(r['ease'], r['id'], r['topic'], r['question'][:60])
c.close()
"
```
Handy queries: `SELECT topic,COUNT(*) FROM questions GROUP BY topic;` ·
`SELECT qid,COUNT(*) FROM reviews WHERE correct=0 GROUP BY qid;` (your wrongs)
· `SELECT COUNT(*) FROM sr_state WHERE due<=date('now');` (due today).

### Maintain
| Task | Command |
|---|---|
| Re-chunk + re-embed after editing a `.md` (idempotent — skips already-done) | `.venv/bin/python -m src.chunker` |
| Re-insert the 100 seed questions (idempotent — skips if already loaded) | `.venv/bin/python -m seeds.seed_questions` |
| Insert questions from a JSON file (per-source idempotent) | `.venv/bin/python -m src.ingest <file.json>` (format: `[{topic,source_file,question,opts[4],correct,explanation}]`) |
| Back up the whole bank + vectors + history | `cp ./revize.db /var/backups/revize-backup-$(date +%F).db` |

> `revize.db` is one SQLite file containing questions, the review log, SM-2
> state, text chunks, **and** the vector index. Back it up by copying it. It's
> WAL-mode, so a `cp` of just the `.db` is consistent enough when the bot is
> idle; for a guaranteed-clean backup stop the bot first (`sudo systemctl stop
> revize-bot`).

## 5. The ingestion process (adding new books)

The book-watcher (`revize-watcher.service`) watches
`./inbox/`. Drop an ebook in; it does the rest:

1. **Drop** a book (`.epub` / `.pdf` / `.mobi` / `.azw` / `.txt` / `.md`) into
   `./inbox/`.
2. Within ~15 s (once the file size is stable) the watcher hands it to
   **ai-agent**, which: converts to markdown → chunks + embeds into the vector
   DB → authors **50 beginner-to-intermediate MCQs** from the text → inserts
   them into the bank (each with `due=today`, so they enter rotation
   immediately). The **topic is auto-inferred** (it prefers an existing topic
   — Beginner Networking / CREST CPSA / OPNsense / Pentesting — and otherwise
   derives one from the book's subject; e.g. the Zero-Trust book became its
   own "Zero Trust" topic).
3. **You get a SimpleX text** when it finishes:
   `revize ingest done — <file>: N chunks, 50 questions, topic: <T>`.
   (If ai-agent bails without inserting, you get a `FAILED` text instead.)
4. The processed book is **moved to `./inbox/done/`** so the
   inbox stays clean and a future same-named book re-ingests fresh.

### Watching / controlling ingestion
| Task | Command |
|---|---|
| Watch ingestion live | `sudo journalctl -u revize-watcher -f` |
| Watcher's own log | `tail -f ~/.revize-watcher/watcher.log` |
| See processed-book history | `cat ~/.revize-watcher/state.json` |
| Restart the watcher | `sudo systemctl restart revize-watcher` |
| Retry a failed book | move it back into `./inbox/` (it's already in `done/`? `mv done/<book> .`), then the watcher re-hands it off. Re-inserting a book whose questions already exist is a no-op (per-source guard). |

### Add questions manually (without the watcher)
Write a JSON file (`[{topic, source_file, question, opts:[4], correct:"A".."D", explanation}, …]`) and:
```bash
cd . && .venv/bin/python -m src.ingest /path/to/your.json
```
The `source_file` should be the `.md` basename the questions refer to (so the
QuizBot's `teach` can retrieve matching chunks). Per-source idempotent.

## 6. Service management & logs

Three systemd services run revize (all auto-start at boot):
| Service | What | Logs |
|---|---|---|
| `revize-bot` | the QuizBot daemon (SimpleX pty + quiz loop + RAG tutor) | `sudo journalctl -u revize-bot -f` (also `~/.simplex-quizbot/quizbot.log`, `quizbot-pty.log`) |
| `revize-watcher` | book-ingestion watcher | `sudo journalctl -u revize-watcher -f` (also `~/.revize-watcher/watcher.log`) |
| `ollama` | the local LLM server (Qwen2.5 7B + nomic-embed-text) | `sudo journalctl -u ollama -f` |

Common commands:
```bash
sudo systemctl restart revize-bot          # reload after code/config changes
sudo systemctl status  revize-bot         # is it running?
sudo systemctl stop    revize-bot         # for a clean DB backup / QR re-setup
sudo systemctl restart revize-watcher     # after watcher code changes
systemctl is-enabled revize-bot revize-watcher   # should both say 'enabled'
ollama list                               # installed models
curl -s http://127.0.0.1:11434/api/tags   # ollama API health + models
```

## 7. Troubleshooting

**The bot didn't message me this morning.**
- `systemctl is-active revize-bot` → should be `active`. If `failed`,
  `sudo journalctl -u revize-bot -n 50` to see why.
- Kickoff only fires once/day after 08:00. If the daemon restarted today
  after 08:00 it may have already "used" today's kickoff — text `quiz` to
  start manually.
- `~/.simplex-quizbot/quizbot-pty.log` — if simplex-chat isn't connecting,
  the raw pty stream shows it. The profile/contact must exist (one-time QR
  setup; see `GUIDE.md` §13).

**I answered but got no reply.**
- The bot polls every 2 s; allow ~3 s. If still nothing,
  `sudo journalctl -u revize-bot -f` and check `[bot] <- …` lines appear for
  your reply. If not, the inbound poll isn't seeing your message — the
  QuizBot profile may have lost its contact; re-run `setup-quizbot.sh` only
  with the service stopped.
- A reply that isn't `a/b/c/d` or a command gets *"Send a/b/c/d …"*.

**`teach` replied "I don't have that in my notes".**
- That's correct behaviour, not a bug: the topic isn't covered by your chunked
  books. Either drop a relevant book into the inbox, or `teach` a topic you
  know is in the bank (check `python -m src.books`).

**A watcher ingest texted `FAILED: ai-agent finished but 0 questions in DB`.**
- ai-agent ran but didn't author/insert (rare). Move the book back into
  `./inbox/` from `done/` and let it retry; if it fails again,
  check `~/.revize-watcher/watcher.log` for the ai-agent stderr and consult
  `GUIDE.md` §15.

**`quiz hard` says "No questions match".**
- You haven't gotten anything wrong yet — there are no weak spots to drill.
  Use `quiz` (mixed) or `quiz new` (fresh cards) instead.

**Ollama / the LLM seems off (teach is empty or errors).**
- `systemctl is-active ollama` and `curl -s http://127.0.0.1:11434/api/tags`
  (should list qwen2.5 + nomic-embed-text). If down:
  `sudo systemctl restart ollama`. First call after idle takes a few seconds
  to load the model into VRAM — that's normal.

**Performance / GPU.** The 7B only loads during a `teach`/wrong-answer call
and unloads ~5 min later; the rest of the time the GPU is idle. If you ever add
a second bot, see `GUIDE.md` for the VRAM budget (8 GB → one 7B resident at a
time).

## 8. Where to look for everything

| Want to… | See |
|---|---|
| Answer questions / steer sessions | §2–§3 (phone) |
| See your accuracy / topics | `stats` / `topics` over SimpleX, or `python -m src.stats` in shell (§4) |
| List ingested books | `python -m src.books` (§4) |
| Add a new book | drop it in `./inbox/` (§5) |
| Add questions manually | `python -m src.ingest <json>` (§5) |
| Restart / check services | §6 |
| Understand internals / extend the code | `GUIDE.md` |

— End of USER_GUIDE. For architecture, data model, and developer notes, read `GUIDE.md`.




