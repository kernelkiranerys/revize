# revize — spaced-revision QuizBot over SimpleX

A self-hosted revision bot that messages you one MCQ each morning and keeps
the conversation going while you reply. Wrong answers can be explained by a
local LLM (Qwen2.5 7B) grounded in your own textbooks (RAG over sqlite-vec).
Questions are authored, never generated at runtime.

## Components (all in .)
- `revize.db` — one SQLite file: questions, reviews log, SM-2 state, text chunks + vec_chunks.
- `src/db.py` — schema + CRUD + sqlite-vec search.
- `src/chunker.py` — markdown chunker + Ollama embedder (`python -m src.chunker`).
- `src/scheduler.py` — SM-2 spaced repetition.
- `src/grader.py` — parse A/B/C/D, grade, log.
- `src/tutor.py` — RAG (retrieve chunks → Ollama chat, sandboxed prompt).
- `src/simplex_io.py` — QuizBot SimpleX pty + DB poll (adapted from ~/simplex-bridge/bridge.py).
- `src/bot.py` — daemon: 08:00 kickoff + reactive ping-pong (`python -m src.bot`).
- `prompts/{explain,teach}.txt` — version-controlled, LLM cannot change them.
- `seeds/seed_questions.py` — the 100 authored questions (idempotent loader).

## Launch sequence (do in order)

### 1. Ollama (CUDA) — one sudo rebuild
    sudo cp ./nix-ollama.nix /etc/nixos/ollama.nix
    # add  ./ollama.nix  to the imports list in /etc/nixos/configuration.nix
    sudo nixos-rebuild switch
    ollama pull qwen2.5:7b-instruct-q4_K_M
    ollama pull nomic-embed-text

### 2. Embed the 16 textbooks into the vector DB
    ./.venv/bin/python -m src.chunker
    (one-time; ~16 books × a few hundred chunks each; re-run when you add books)

### 3. One-time QuizBot profile + contact QR
    bash ./setup-quizbot.sh
    # follow the on-screen steps: /c -> scan link on phone -> send 'hi' -> /q

### 4. Start the bot service
    sudo cp ./nix-revize.nix /etc/nixos/revize.nix
    # add  ./revize.nix  to imports in /etc/nixos/configuration.nix
    sudo nixos-rebuild switch
    sudo systemctl enable --now revize-bot
    sudo journalctl -u revize-bot -f

## Using it (from your phone, in the QuizBot chat)
- It pushes one due question at 08:00; replies keep the session going.
- `a`/`b`/`c`/`d` — answer · `teach` — RAG lesson on the current Q · `skip` — counts wrong, moves on
- `stop` — pause · `quiz`/`go` — start/resume · `stats` — your accuracy · `help`

## Adding new books (watcher pipeline — to be built)
Drop an ebook into ./inbox → watcher messages ai-agent → ai-agent
converts to .md, chunks+embeds, authors ~50 questions, inserts into revize.db.
