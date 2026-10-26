# revize — Spaced-Revision QuizBot (full project guide)

> A self-hosted revision bot that quizzes you over SimpleX Chat from your own
> cybersecurity/networking textbooks, with a local LLM that only *explains* —
> it never writes questions, grades, or schedules. This document is the single
> source of truth: a fresh LLM session with no prior context should be able to
> continue the build or modify it using only this file + the code under
> `./`.

---

## 1. What revize is

revize is a personal **spaced-repetition revision bot** that runs as a systemd
service on a NixOS workstation and talks to the user over **SimpleX Chat** on
their phone. Its one job: each morning it opens a conversation with a multiple-
choice question drawn from the user's own library of converted textbooks, and
it keeps the conversation going — answer → grade → next question — for as long
as the user keeps replying. When the user gets one wrong, or asks for a lesson,
a small **self-hosted LLM** (Qwen2.5 7B, GPU) explains the concept, grounded by
RAG over the textbook chunks stored in a local vector database.

It is **not** a question generator. The question bank is authored (by ai-agent,
using larger models, offline) and stored in SQLite. The on-device LLM is
deliberately under-powered on purpose — it only rephrases rationales and
teaches from retrieved context. All control flow (scheduling, grading, session
state, retrieval scope) is deterministic Python.

### Intended use
- Daily, low-friction revision of certification material (CompTIA Network+,
  Security+/CySA+/CSA+, OPNsense, pentesting/Nmap/malware analysis) while the
  user is away from a keyboard, via the phone.
- Spaced repetition (SM-2) so poorly-known questions resurface sooner.
- Conversational remediation: a wrong answer triggers a grounded explanation
  from the actual source text, not a hallucination.

### Topics currently in the bank (seed of 100 questions)
- Beginner Networking (25) — from the three CompTIA Network+ texts
- CREST CPSA study (25) — from Security+/CySA+/CSA+ texts
- OPNsense usage (25) — from the two OPNsense texts
- Pentesting & cyber fundamentals (25) — from Nmap/McNab/Malware/RTFM texts

---

## 2. Design philosophy (read this first)

1. **Deterministic framework, tiny LLM for talk only.** The LLM (Qwen2.5 7B) is
   only invoked to (a) rephrase an answer's rationale and (b) teach a concept
   from retrieved chunks. It is sandboxed behind version-controlled prompt
   templates (`prompts/*.txt`) that forbid inventing facts. It **never** picks
   the next question, grades an answer, sets an interval, or chooses what to
   retrieve. All of that is fixed Python logic.
2. **Questions are authored, not generated at runtime.** Authoring 50
   high-quality MCQs per book is done offline by ai-agent with a capable model;
   results are inserted into `revize.db`. The 7B would produce low-quality
   questions and waste GPU — so it is not asked to.
3. **One file for everything data.** `revize.db` is a single SQLite database
   holding the question bank, the review log, the SM-2 state, the text chunks,
   **and** the vector index (via the `sqlite-vec` extension). No Postgres, no
   separate vector server.
4. **Isolated SimpleX profile.** The bot runs its own `simplex-chat` profile
   (`~/.simplex-quizbot/`) and its own contact on the user's phone ("QuizBot"),
   completely separate from the existing ai-agent↔SimpleX bridge
   (`~/simplex-bridge/`, contact `my-contact`). No shared DB, no contention.
5. **No silence timer.** A session stays open until the user texts `stop` (or
   the daemon restarts). The poller simply idles between replies.
6. **Strict, predetermined procedure.** Cadence, message format, SR parameters,
   chunk size, retrieval depth, and prompt content are all fixed in code/config
   and documented here — not invented by the model at runtime.

---

## 3. Architecture

```
                         ┌──────────────── revize-bot daemon (Python) ────────────────┐
                         │                                                            │
SimpleX phone ◄────────►│  simplex_io  (pty: simplex-chat -a, own profile)            │
   (QuizBot contact)     │      └─ poll chat_items DB for inbound; send via pty        │
                         │                                                            │
                         │  bot.py  ── 08:00 maybe_kickoff() + reactive loop           │
                         │      ├─ grader  (parse A/B/C/D, exact-match, log)           │
                         │      ├─ scheduler (SM-2: ease/interval/due)                 │
                         │      ├─ pick next due question                              │
                         │      └─ tutor (only on wrong/teach)                         │
                         │            ├─ retrieve top-5 chunks (sqlite-vec)            │
                         │            └─ Ollama /api/chat (Qwen2.5 7B) — sandboxed     │
                         │                                                            │
        revize.db ◄──────┤  (questions · reviews · sr_state · chunks · vec_chunks)     │
                         │  db.py  ── schema + CRUD + sqlite-vec load + cosine search   │
                         │  chunker.py ── md→chunks + /api/embed (nomic-embed-text)     │
                         └────────────────────────────────────────────────────────────┘
                                              ▲
   ./data/*.md ─────────────┘  (16 converted textbooks, chunked+embedded once)
```

The daemon is a long-running loop: every `POLL_INTERVAL` (2 s) it checks the
QuizBot SimpleX DB for new inbound messages, routes each through `bot.handle()`,
and once per day at `KICKOFF_HOUR` (08:00) it proactively sends the first due
question to start the conversation.

---

## 4. File layout

```
./                  # project root (also WorkingDirectory of the systemd unit)
├── revize.db                       # the ONE sqlite file (data + vectors)
├── .venv/                          # python venv: sqlite-vec, requests (+ stdlib)
├── config via src/config.py        # all tunables (no toml)
├── src/
│   ├── __init__.py
│   ├── config.py                   # paths, model names, SR defaults, cadence, chunk params
│   ├── db.py                       # schema, connect() loads sqlite-vec, CRUD, vec search
│   ├── chunker.py                  # md→chunks (heading-aware, ~500 tok/50 overlap), embed()
│   ├── scheduler.py                # SM-2 update() + record() (log review + update SR)
│   ├── grader.py                   # parse_answer(), is_command(), grade()
│   ├── simplex_io.py               # QuizBot class: pty simplex-chat + read-only DB poll
│   ├── tutor.py                    # retrieve() + explain() + teach() (RAG → Ollama chat)
│   └── bot.py                      # daemon: maybe_kickoff(), handle(), run(); entry point
├── prompts/
│   ├── explain.txt                 # sandboxed template for explaining a wrong/right answer
│   └── teach.txt                   # sandboxed template for a free-form topic lesson
├── seeds/
│   └── seed_questions.py           # the 100 authored MCQs as a list of dicts + idempotent loader
├── systemd/                        # (reference; actual unit is declared in nix-revize.nix)
├── nix-ollama.nix                  # NixOS module: services.ollama (enable + package=ollama-cuda)
├── nix-revize.nix                  # NixOS module: systemd.services.revize-bot
├── setup-ollama-and-embed.sh       # steps 1+2: install Ollama, pull models, embed 16 books
├── setup-quizbot.sh                # step 3: one-time interactive simplex-chat profile + /c QR
├── README.md                       # short operator quickstart
└── GUIDE.md                        # this file
```

### Other key locations on the host
| Path | What |
|---|---|
| `./data/*.md` | the 16 converted textbooks (source for chunking) |
| `./bridge.py` | the EXISTING ai-agent↔SimpleX bridge (reference, do not modify while running) |
| `~/.simplex/simplex_v1_chat.db` | the ai-agent bridge's SimpleX DB (untouched by revize) |
| `~/.simplex-quizbot/simplex_v1_chat.db` | revize QuizBot's own SimpleX DB |
| `~/.simplex-quizbot/files/` | QuizBot files folder |
| `/etc/nixos/flake.nix` | NixOS flake; modules list includes `./ollama.nix` (and later `./revize.nix`) |
| `/etc/nixos/ollama.nix` | copy of `nix-ollama.nix` (installed by the setup script) |
| `/var/lib/ollama/models/` | Ollama model blobs (qwen2.5 7B q4 ~4.4 GB, nomic-embed-text ~0.27 GB) — on root fs |
| `/run/current-system/sw/bin/ollama` | the ollama CLI (module adds it to systemPackages) |

## 5. Data model (`revize.db`, one SQLite file)

`db.connect()` opens the DB, enables `load_extension`, loads the `sqlite-vec`
shared library (path resolved by the `sqlite-vec` Python package), sets
WAL + foreign keys. `db.init_db()` creates everything idempotently.

### Tables
- **questions**(`id` PK, `topic`, `source_file`, `question`, `opt_a..d`,
  `correct` [letter A-D], `explanation`, `difficulty` default 'intermediate',
  `created`). One row per MCQ.
- **reviews**(`id` PK, `qid`, `ts`, `given`, `correct` [0/1], `latency_s`,
  `session_id`). Immutable append-only log of every answer.
- **sr_state**(`qid` PK, `ease` default 2.5, `interval_days` default 0,
  `reps` default 0, `due` [ISO date], `last_reviewed`). One row per question,
  the SM-2 working state. Seeded with `due=today` so everything is immediately
  due on day one.
- **chunks**(`id` PK, `source_file`, `heading`, `ordinal`, `text`). One row per
  text chunk; `source_file` is the `.md` basename (e.g.
  `Nmap Network Scanning.md`).
- **vec_chunks** — `CREATE VIRTUAL TABLE … USING vec0(embedding float[768],
  chunk_id integer)`. sqlite-vec virtual table; `chunk_id` foreign-references
  `chunks.id`. Cosine distance search via `WHERE embedding MATCH ? AND k=?`.
- **meta**(`k` PK, `v`) — arbitrary state, e.g. `last_kickoff_date`.

### Key queries (see `db.py`)
- Due selection: `SELECT qid FROM sr_state WHERE due<=? [AND qid NOT IN (...excluded)] ORDER BY due LIMIT ?`
  — the exclude list is **omitted entirely** when empty (a previous
  `NOT IN (NULL)` form silently dropped every row; see §13 gotchas).
- RAG search (scoped): `… WHERE v.embedding MATCH ? AND k=? AND c.source_file=? ORDER BY v.distance`
  (global variant omits the `source_file` filter).
- `chunks_for_source(source_file)` — used by ingestion.

### Seeded questions
`seeds/seed_questions.py` holds the 100 authored MCQs as a `QUESTIONS` list of
dicts (`topic, source_file, question, opts[4], correct, explanation`). Its
`load()` is idempotent: it skips if `COUNT(questions) >= len(QUESTIONS)`. Each
entry is inserted via `db.add_question()`, which also creates the matching
`sr_state` row (`due=today`). Options are stored **with** the `A) ` prefix so
they render directly in chat messages. Run re-seed any time:
```bash
./.venv/bin/python -m seeds.seed_questions
```
To **add more questions** (e.g. a new book's 50), append dicts to `QUESTIONS`
(or write a parallel seed file) and re-run the loader; existing ids are not
re-inserted because the count guard + `add_question`'s AUTOINCREMENT keep
them stable. (For a brand-new seed file, ensure the count guard matches.)

## 6. The quiz process (session lifecycle)

A "session" is a stretch of ping-pong on the QuizBot conversation. It is **not**
time-boxed — see philosophy §2.5.

1. **Kickoff** — `bot.maybe_kickoff()` fires once per day when local hour ≥
   `KICKOFF_HOUR` (08:00) and no question is already pending. It clears the
   session's `asked` set, resets the answered counter, messages
   "☀ Morning revision — here's your first question." and calls
   `send_question()`. It records `last_kickoff_date` (also persisted to
   `meta`) so it won't fire twice in one day. Note: there is **no separate
   systemd timer** — the trigger is internal to the long-running daemon.
2. **Ping-pong** — `bot.handle(text)` parses the first word as the command and
   the rest as its argument, then routes:
   - `a/b/c/d` (or `1-4`, or "answer: d") → `grader.grade()` →
     `scheduler.record()` (logs the review + runs SM-2) → send feedback +
     `send_question()` for the next one (respecting the active filter).
   - `quiz` / `go` / `next` → start/resume a **mixed** SM-2 session.
   - `quiz <topic>` → session filtered to one topic (case-insensitive, partial
     match; e.g. `quiz opnsense`, `quiz "zero trust"`).
   - `quiz new` → session of **fresh cards** only (questions with `reps=0`).
   - `quiz hard` → session of **weak spots** (questions with ≥1 wrong review).
   - `teach` / `explain` → if a question is pending, `tutor.explain(current_qid,
     None)`; else `tutor.teach(<rest>)` (free-form RAG lesson on a topic).
   - `skip` → record current as wrong (sooner re-schedule), send next.
   - `stop` → clear pending question + reset the filter, send "Session paused".
   - `stats` → overall accuracy/due; `stats <topic>` → per-topic.
   - `topics` → list all topics with question counts.
   - `help` → command list. Anything unparseable → "Send a/b/c/d …".
   The active **session filter** (`self.filter = (topic, mode)`) is set by the
   `quiz` command and sticks across answers until you change it or `stop`.
3. **No silence close** — the loop just keeps polling; a forgotten conversation
   costs nothing until the next inbound. A soft nudge line ("still going?") is
   inserted every `SOFT_NUDGE_AFTER` (25) answered questions.
4. **Question selection** — `pick_question(topic, mode)` calls
   `db.get_due_qids(topic=, mode=)` (most-overdue due qid, excluding
   already-asked this session). `mode` adds `reps=0` ("new") or an
   `EXISTS reviews correct=0` ("hard") clause; `topic` adds a `LOWER(topic)
   LIKE` clause. In default mode only, if nothing is due it falls back to a
   random not-yet-asked question so the bank never stalls. Filtered modes with
   no matches reply "No questions match …" rather than falling back.

## 7. Message protocol (plain text, no markdown)

SimpleX renders markdown as raw punctuation on a phone, so all bot output is
plain text with simple newlines. Every question message is:
```
Q42 (Networking)
Which OSI layer packages data into frames?
A) Network
B) Data Link
C) Transport
D) Physical
Reply a/b/c/d · 'teach' for a lesson · 'skip' · 'stop'
```
Feedback on correct:
```
✓ Correct — Data Link layer PDUs are frames; Network = packets.

Next Q18 (CPSA): …
```
Feedback on wrong:
```
✗ It's B. One-line why: PDUs at Layer 2 are frames; Layer 3 = packets.
Reply 'teach' for the full lesson, or answer the next:
Next Q18 (CPSA): …
```
`teach` reply: the RAG lesson (≤200 words) + "Reply for the next question, or
'teach' again." Replies are truncated to `MAX_REPLY_CHARS` (3900) to stay
under SimpleX's ~4000-char trim.

## 8. Spaced repetition — SM-2 (`scheduler.py`)

Standard SM-2, parameterised in `config.py`:
- `ease0 = 2.5`, `EASE_MIN = 1.3`, correct → `quality = 5`, wrong → `quality = 2`.
- Correct: `reps==0 → interval=1`; `reps==1 → interval=6`; else
  `interval = round(interval * ease)`; `reps += 1`.
- Wrong: `reps = 0`, `interval = 1` (full restart).
- Ease update: `EF' = EF + (0.1 − (5−q)·(0.08 + (5−q)·0.02))`, clamped to ≥ 1.3.
- `due = today + interval` (ISO date).

`scheduler.record(qid, given, correct, latency_s, session_id)` is the entry
point: it writes the `reviews` row, then calls `update(qid, quality)` which
recomputes SM-2 and persists via `db.put_sr()`. Quality defaults from
correctness but can be overridden (future v2: Anki-style self-grade
`again/hard/good/easy`).

## 9. RAG tutor (`tutor.py` + `prompts/`)

The only place the LLM is invoked. Two modes:

- **`explain(qid, given_letter)`** — used on a wrong answer (or an explicit
  `teach` with a pending question). Embeds
  `question + explanation`, retrieves **top-5 chunks scoped to that question's
  `source_file`** (so a Networking question only pulls from the Network+
  books), builds the prompt from `prompts/explain.txt`, calls
  `POST /api/chat` (Qwen2.5 7B, `num_predict=300`, `temperature=0.3`).
- **Conversational teach mode** (`start_lesson` / `continue_lesson`) —
  `teach <topic>` opens a multi-turn conversation. The bot resolves the topic's
  books (`db.source_files_for_topic`) and locks retrieval to that set; each
  follow-up re-retrieves top-5 chunks within the scope and is appended (with its
  context block) as a new user turn, while the assistant's prior turns stay in
  the `messages[]` history sent to `/api/chat` — so the user can drill into
  sub-topics and the thread stays coherent. `_trim` keeps the last ~12 turns.
  `prompts/teach_chat.txt` is the system prompt (use ONLY this turn's context;
  don't invent; plain text; suggest a next drill-down). With a question pending,
  bare `teach` scopes to that question's `source_file`. Free-form subjects (no
  topic match) retrieve globally. The legacy one-shot `teach(topic)` is retired
  in favour of `start_lesson`.

### Prompt templates (version-controlled, the LLM cannot change them)
`prompts/explain.txt` (one-shot quiz rationale), `teach_chat.txt` (conversational
tutor) and `teach.txt` all carry a hard SYSTEM line: *"Use ONLY the context
chunks provided. If the answer is not in the context, say 'I don't have that in
my notes' and stop. Do NOT invent facts, numbers, or commands. Plain text only —
NO markdown, NO tables, NO code fences."* Placeholders (`{CHUNKS}`, `{QUESTION}`,
`{OPTIONS}`, `{CORRECT}`, `{GIVEN}`, `{VERDICT}`, `{TOPIC}`) are filled by plain
`str.replace` (not `.format`, so chunk text containing braces is safe). Each chunk
block is formatted `[source_file / heading] <text[:600]>`. All LLM replies pass
through `_strip_md` (strips `**`/backticks/heading marks, normalises bullets) so
they render cleanly as plain text on SimpleX.

### What Qwen2.5 is forbidden to do
Pick questions, grade answers, set intervals, decide retrieval scope, choose
when a session starts/stops, or modify any state. It receives one system
prompt and returns prose. Everything else is Python.

## 10. SimpleX transport (`simplex_io.py`)

A `QuizBot` class that owns one `simplex-chat` process in a pty, mirroring the
**proven design of the existing ai-agent bridge** at
``./bridge.py`` (read it if extending the transport).

### Isolation
It runs its **own** SimpleX profile via a separate database prefix:
```
simplex-chat -y -a -d ~/.simplex-quizbot/simplex_v1 \
  --files-folder ~/.simplex-quizbot/files --mute
```
(`-d` takes the prefix; the chat DB becomes
`~/.simplex-quizbot/simplex_v1_chat.db`.) This is a different profile from the
ai-agent bridge's `~/.simplex` — the two never touch the same DB.

### Outbound
Replies are **typed into the pty** as `@<contact_name> <msg>\n` (not via
`simplex-chat -e`, which is a second client and "steals routing" — a lesson
learned in the ai-agent bridge). `send()` resolves the contact first
(`resolve_contact()` finds the single non-user contact in `contacts`,
preferring one literally named `QuizBot`).

### Inbound (read-only DB poll)
The same query the ai-agent bridge uses, pointed at the QuizBot DB:
```sql
SELECT chat_item_id, item_text FROM chat_items
WHERE contact_id=? AND item_sent=0 AND item_deleted=0 AND chat_item_id>?
ORDER BY chat_item_id ASC
```
`item_sent=0` = received (inbound); `item_deleted=0` = live. A high-water mark
(`~/.simplex-quizbot/last_id`) ensures only messages newer than the last poll
are returned. On first run the mark is set to the current max so the bot does
not replay history.

### Lifecycle inside the daemon
`bot.run()` calls `sx.start()` (spawn pty, wait for the `Current user:` /
`subscribed` readiness marker, up to 40 s), then loops every
`POLL_INTERVAL` (2 s): restart simplex-chat if it died; `maybe_kickoff()`;
drain `sx.new_messages()`; route each through `handle()`. SIGTERM/SIGINT flip
`running=False` and the loop exits cleanly, killing the pty.

## 11. Toolchain & versions

| Component | What / version |
|---|---|
| OS | NixOS 26.05, **flake-based** (flake at `/etc/nixos/flake.nix`, attr `nixosConfigurations.nixos`) |
| Shell transport | `simplex-chat v7.0.0.12` (system package; `-d` selects profile) |
| Python | 3.13 (system) via a local venv at `./.venv` |
| Python deps | `sqlite-vec 0.1.9`, `requests 2.34.2` (+ stdlib only — no torch, no langchain) |
| LLM runtime | Ollama via the NixOS `services.ollama` module (`package = pkgs.ollama-cuda`) |
| Chat model | `qwen2.5:7b-instruct-q4_K_M` (~4.4 GB, GPU) |
| Embedding model | `nomic-embed-text` (768-dim, ~0.27 GB) |
| Embedding API | `POST /api/embed` `{model,input}` → `{embeddings:[[...]]}` (with `/api/embeddings` 404-fallback for older Ollama) |
| Chat API | `POST /api/chat` `{model,messages,stream:false,options:{num_predict,temperature}}` |
| Vector store | `sqlite-vec` virtual table inside `revize.db` (no server) |
| SR algorithm | SM-2 (in-process Python) |

No Docker, no separate DB server, no queue. One Python process + one
`simplex-chat` process + one `ollama` service.

## 12. Machine context (where this runs)

- **CPU:** Intel Xeon W-2235 @ 3.80 GHz, 6 cores / 12 threads.
- **RAM:** 125 GB (~88 GB free) — abundant; not a constraint.
- **GPU:** NVIDIA Quadro RTX 4000, **8 GB VRAM** (Turing; proprietary driver
  already configured in `configuration.nix` via `hardware.nvidia`). Qwen 7B
  Q4 fits comfortably with room for context.
- **Disk:** root `/` 915 GB (209 GB free); `/mnt/secondary` 7.3 TB ext4
  (3.2 TB free, holds the textbooks + isos); `/mnt/secondary` 1.9 TB.
- **Build system:** NixOS flake. `/etc/nixos` is **not** a git repo, so the
  flake sees every file directly (no `git add` needed). The flake's `modules`
  list explicitly names each `.nix` (there is **no** `imports = [...]` line in
  `configuration.nix`). Rebuild: `sudo nixos-rebuild switch --flake /etc/nixos#nixos`.

## 13. Build & launch sequence (operator steps)

These are the *user-facing* steps; steps 1–2 are automated by
`setup-ollama-and-embed.sh`.

1. **Ollama + embeddings** — `bash ./setup-ollama-and-embed.sh`.
   Copies `nix-ollama.nix`→`/etc/nixos/ollama.nix`, idempotently inserts
   `./ollama.nix` into `flake.nix`'s modules list, runs
   `sudo nixos-rebuild switch --flake /etc/nixos#nixos` (**first time ~10–20
   min**: ollama-cuda builds from source + ~314 MiB CUDA blobs fetched from
   NVIDIA — this is expected, not a failure), waits for `ollama.service`,
   pulls `qwen2.5:7b-instruct-q4_K_M` + `nomic-embed-text`, then runs
   `python -m src.chunker` to chunk + embed the 16 `.md` books.
2. (covered by step 1's chunker run — re-run `python -m src.chunker` any time
   a new book is added; it skips already-embedded sources).
3. **One-time QuizBot contact** — `bash ./setup-quizbot.sh`
   launches `simplex-chat` interactively on the QuizBot profile. In its prompt:
   `/c` (create contact invitation) → scan/paste the link on the phone's
   SimpleX app → send "hi" (should appear in the terminal) → `/q` to quit. The
   profile + contact are now persisted; the daemon will reuse them.
4. **Start the service** — add `./revize.nix` to `flake.nix`'s modules list,
   `sudo nixos-rebuild switch --flake /etc/nixos#nixos`, then
   `sudo systemctl enable --now revize-bot`. Watch with
   `sudo journalctl -u revize-bot -f`.

## 14. Current state of the build (as of this writing)

**Done & tested (no Ollama required):**
- Project scaffold + venv (`sqlite-vec`, `requests`).
- `revize.db` schema incl. `vec_chunks` virtual table; loads sqlite-vec.
- 100 questions seeded (25/topic); counts verified.
- `chunker.py` (md→chunks, `/api/embed` embed), `scheduler.py` (SM-2 math
  verified: ease 2.5→2.6→2.7, wrong→2.38 reset), `grader.py` (parse cases
  verified), `simplex_io.py`, `tutor.py` + both prompts, `bot.py` main loop.
- NixOS modules `nix-ollama.nix` (fixed: `package=ollama-cuda`) and
  `nix-revize.nix`; setup scripts; `README.md`.
- Due-query bug fixed (`NOT IN (NULL)`→ proper exclude handling).

**Pending (needs the operator):**
- Step 1 actually completing (Ollama rebuild + model pulls + chunker embed run)
  — was in progress when this guide was written.
- A RAG smoke-test (`tutor.explain` on a real qid) once Ollama is up, *before*
  the QR step — to confirm the Qwen+nomic path end-to-end.
- Step 3 (QR scan) + Step 4 (wire `revize.nix` into flake + enable service).
- End-to-end test over SimpleX.

**Not yet built (spec'd in §15):** the book-watcher pipeline.

## 15. Book-watcher pipeline (built)

Drop a new ebook into `./inbox/` and it is ingested end-to-end
with no manual steps: convert → chunk+embed → author 50 MCQs → insert into
`revize.db`, then a SimpleX text confirms it on your phone. The on-device 7B is
**not** involved (it only quizzes on the resulting bank) — the heavy lifting is
done by `ai-agent run` (big-model capacity), keeping the "author offline, quiz
online" boundary (§2). Decisions locked: **auto-infer topic**, **auto-insert**
(no review queue), **50 questions/book**.

Flow:
1. `revize-watcher.service` (`src/watcher.py`) polls `./inbox`
   every 10 s. When a new file's size is stable for ~15 s (download finished),
   it marks the file `processing` in `~/.revize-watcher/state.json` and hands off.
2. It spawns `ai-agent run "<directive>" --dir ~
   --dangerously-skip-permissions --format json` (30-min timeout; directive in
   `prompts/ingest_directive.txt`, `{PATH}` substituted). ai-agent:
   a. `bash ./convert-book.sh "<path>"` — deterministic
      converter: epub→`nix shell nixpkgs#pandoc -c pandoc`, pdf→`poppler-utils`
      `pdftotext -layout`, mobi/azw→calibre `ebook-convert`, txt/md→copy;
      output `./data/<stem>.md`.
   b. `python -m src.chunker` — idempotent chunk+embed of new sources.
   c. Reads the .md, mines ~60 verbatim facts, authors exactly 50 MCQs as JSON
      (`{topic, source_file, question, opts[4] bare, correct, explanation}`),
      inferring `topic` (prefers an existing one: Beginner Networking / CREST
      CPSA / OPNsense / Pentesting; else derives one from the book's subject).
   d. `python -m src.ingest /tmp/revize_ingest_<stem>.json` — inserts into
      `revize.db` via `db.add_question()` (each gets an `sr_state` row,
      `due=today` so it enters rotation immediately). Per-source idempotent:
      skips if `source_file` already has questions.
3. The watcher writes ai-agent's one-line summary to `~/.simplex-bridge/outbox`;
   the existing ai-agent bridge picks it up and texts your phone (`my-contact`)
   via its pty. State for the file becomes `done` (or `failed` + you're notified).

Files: `src/watcher.py`, `src/ingest.py`, `convert-book.sh`,
`prompts/ingest_directive.txt`, `nix-watcher.nix`, `setup-watcher.sh`.
Install: `bash ./setup-watcher.sh` (idempotent flake wiring +
rebuild + enable). Live log: `sudo journalctl -u revize-watcher -f`.

## 16. Operational notes

### Logs & debugging
- **Daemon logs:** `sudo journalctl -u revize-bot -f` (also `~/.simplex-quizbot/quizbot.log` for the bot's own `_log()` lines, and `~/.simplex-quizbot/quizbot-pty.log` for the raw simplex-chat pty stream — essential if sending/receiving looks wrong).
- **Ollama:** `sudo journalctl -u ollama -f`; API health `curl -s http://127.0.0.1:11434/api/tags`.
- **DB inspection:** `sqlite3 ./revize.db` is not on PATH by
  default; use the venv python:
  `./.venv/bin/python -c "from src import db; …"`.
- **Restart the bot:** `sudo systemctl restart revize-bot`.
- **Force a kickoff now** (for testing): `sudo systemctl restart revize-bot`
  then on the phone text `quiz`. Or run `python -m src.bot kickoff` in a
  foreground terminal (kills any service-owned simplex-chat first — stop the
  service first to avoid DB lock).

### Common changes
- **Add a question/topic:** append to `seeds/seed_questions.py` (or a new seed
  file mirroring its shape) and re-run the loader.
- **Change cadence:** edit `KICKOFF_HOUR` / `SOFT_NUDGE_AFTER` in `config.py`.
- **Swap the chat model:** edit `CHAT_MODEL` in `config.py`; `ollama pull` it;
  the prompts stay the same.
- **Tune SR aggressiveness:** change `QUAL_CORRECT`/`QUAL_WRONG` or wire a
  self-grade override in `scheduler.record`.
- **Re-embed after editing a book:** delete its `chunks` + `vec_chunks` rows
  (`DELETE FROM vec_chunks WHERE chunk_id IN (SELECT id FROM chunks WHERE source_file=?); DELETE FROM chunks WHERE source_file=?;`) then re-run `python -m src.chunker`.

## 17. Gotchas & landmines (already hit — don't repeat)

1. **`services.ollama.acceleration` is gone in nixos-26.05.** Use
   `services.ollama.package = pkgs.ollama-cuda` (or `-rocm`/`-vulkan`/`-cpu`).
   The module asserts and the rebuild fails cleanly otherwise.
2. **Ollama embeddings API changed:** current is `POST /api/embed`
   (`{model, input}` → `embeddings[0]`). The old `/api/embeddings`
   (`{model, prompt}` → `embedding`) is gone in recent Ollama. `chunker.embed`
   tries `/api/embed` first, falls back to `/api/embeddings` on 404.
3. **`sqlite` "NOT IN (NULL)" drops every row.** `db.get_due_qids` originally
   built `NOT IN (NULL)` when the exclude list was empty, which made *no*
   questions ever appear due. Fixed by omitting the `NOT IN` clause entirely
   when exclude is empty.
4. **NixOS flake ≠ configuration.nix imports.** This box has **no**
   `imports = [...]` in `configuration.nix`; modules are listed in
   `flake.nix`'s `modules = [...]`. New `.nix` files must be added to the
   flake's list, and `/etc/nixos` is not a git repo so files are visible
   without `git add`. Rebuild with `--flake /etc/nixos#nixos`.
5. **`ollama-cuda` is unfree** (CUDA EULA). The system config already has
   `nixpkgs.config.allowUnfree = true`, so `nixos-rebuild` is fine — but a
   bare `nix build nixpkgs#ollama-cuda` errors unless you
   `NIXPKGS_ALLOW_UNFREE=1 … --impure`. It also builds from source the first
   time (~10–20 min) because unfree CUDA isn't in the public Hydra cache.
6. **SimpleX pty, not `-e`.** Send by typing `@<contact> <msg>\n` into the
   `simplex-chat -a` pty. `simplex-chat -e` is a *second client* and races the
   agent for routing — the ai-agent bridge learned this the hard way. revize
   mirrors the pty approach.
7. **One simplex-chat per profile DB.** The QuizBot profile DB
   (`~/.simplex-quizbot/`) is locked by the daemon's `simplex-chat -a`. The
   one-time `setup-quizbot.sh` must run *before* enabling the service (or
   with the service stopped), else the DB is locked and setup can't proceed.
8. **Ollama service is sandboxed** (DynamicUser, ProtectHome, strict
   ProtectSystem). Models live in `/var/lib/ollama/models` (on root, as
   agreed); the user's `ollama pull` is a *client* to the service, not a local
   write. NVIDIA device access is granted via `DeviceAllow` in the module.
9. **Plain text only over SimpleX.** No markdown/tables/code-fences in any bot
   output (renders as garbage on the phone). The prompts explicitly forbid it.
10. **sqlite-vec `vec0` columns take a packed blob, not a Python list.** Binding
    a `list` raises `type 'list' is not supported`. `db._pack(vec)` does
    `struct.pack('<%df' % len(vec), *vec)` (little-endian float32) and is used in
    both `add_chunk` (INSERT) and `search_chunks` (the MATCH vector). nomic-embed-text
    returns 768 floats → 3072-byte blob, matching `float[768]` in the schema.

## 18. Quick index for a fresh LLM session

- "Where's the bot's main loop?" → `src/bot.py` `Bot.run()` + `handle()`.
- "How does it pick the next question?" → `bot.pick_question()` →
  `db.get_due_qids()`.
- "How is an answer graded?" → `grader.grade()` → `scheduler.record()` →
  `db.log_review()` + `scheduler.update()` (SM-2).
- "When does the LLM run?" → only `tutor.explain()` / `tutor.teach()`, via
  `prompts/explain.txt` / `teach.txt`, calling Ollama `/api/chat`.
- "How does it talk to SimpleX?" → `src/simplex_io.py` `QuizBot` class
  (own pty profile, read-only DB poll), pattern copied from
  `./bridge.py`.
- "Where are the questions?" → `seeds/seed_questions.py` (100) → loaded into
  `revize.db` `questions` table.
- "How do I add a book end-to-end?" → see §15 (watcher, spec'd) or manually:
  convert to .md in `./data`, run `python -m src.chunker`,
  author MCQs, `python -m seeds.seed_questions`.
- "What's not done?" → §14 (QR scan, service enable, e2e test, watcher).

— End of GUIDE. Code is the source of truth; this file is the map.





