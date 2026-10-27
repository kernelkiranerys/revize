import os, shutil

# ── paths ────────────────────────────────────────────────────────────────
HOME = os.path.expanduser("~")
SIMPLEX_CHAT_BIN = os.environ.get("SIMPLEX_CHAT_BIN") or shutil.which("simplex-chat") or "/run/current-system/sw/bin/simplex-chat"
PROJECT_DIR = os.path.join(HOME, "revize")
DB_PATH = os.path.join(PROJECT_DIR, "revize.db")
TEXT_DIR = "./data"            # converted .md books live here
WATCH_DIR = "./inbox"            # drop new ebooks here (watcher)

# ── ollama ───────────────────────────────────────────────────────────────
OLLAMA_HOST = "http://127.0.0.1:11434"
CHAT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# ── simplex (QuizBot — its own isolated profile) ────────────────────────
QUIZBOT_DB = os.path.join(HOME, ".simplex-quizbot", "simplex_v1_chat.db")
QUIZBOT_DB_PREFIX = QUIZBOT_DB[: -len("_chat.db")]      # simplex-chat -d wants the prefix
QUIZBOT_FILES = os.path.join(HOME, ".simplex-quizbot", "files")
QUIZBOT_CONTACT = "QuizBot"          # local_display_name you set after scanning the QR
STATE_DIR = os.path.join(HOME, ".simplex-quizbot")   # last_id, pty log, etc.
POLL_INTERVAL = 2.0                  # seconds between inbound checks

# ── session / cadence ────────────────────────────────────────────────────
KICKOFF_HOUR = 8                     # 08:00 daily morning question
# No silence-close: session stays alive until user texts 'stop' or goes idle.
SOFT_NUDGE_AFTER = 25                # after this many answered, send a "still going?" check
MAX_REPLY_CHARS = 3900               # keep under SimpleX's 4000 char trim

# ── ingestion (watcher) ────────────────────────────────────────────────
BOOK_QCOUNT = 50          # MCQs authored per topic-folder book
UNI_LESSON_QCOUNT = 12    # MCQs per uni lesson doc (module handbook = 0, query-only)

# ── RAG / chunking ───────────────────────────────────────────────────────
CHUNK_TOKENS = 500
CHUNK_OVERLAP = 50
TOP_K = 5
EXPLAIN_MAX_TOKENS = 300
TEACH_MAX_TOKENS = 450

# ── SM-2 defaults ────────────────────────────────────────────────────────
SM2_EASE0 = 2.5
SM2_EASE_MIN = 1.3
QUAL_CORRECT = 5
QUAL_WRONG = 2
