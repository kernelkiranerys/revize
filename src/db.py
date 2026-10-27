import sqlite3, os, datetime, struct
import sqlite_vec
from . import config

def _pack(vec):
    """Pack a float list into the little-endian float32 blob sqlite-vec expects."""
    return struct.pack('<%df' % len(vec), *vec)

def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    conn.load_extension(sqlite_vec.loadable_path())
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS questions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT, source_file TEXT,
        question TEXT, opt_a TEXT, opt_b TEXT, opt_c TEXT, opt_d TEXT,
        correct TEXT, explanation TEXT, difficulty TEXT DEFAULT 'intermediate',
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qid INTEGER, ts TEXT, given TEXT, correct INTEGER,
        latency_s REAL, session_id TEXT
    );
    CREATE TABLE IF NOT EXISTS sr_state(
        qid INTEGER PRIMARY KEY,
        ease REAL DEFAULT 2.5, interval_days INTEGER DEFAULT 0,
        reps INTEGER DEFAULT 0, due TEXT, last_reviewed TEXT
    );
    CREATE TABLE IF NOT EXISTS chunks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file TEXT, heading TEXT, ordinal INTEGER, text TEXT
    );
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS books(
        source_file TEXT PRIMARY KEY, topic TEXT, path TEXT, ingested TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_q_topic ON questions(topic);
    CREATE INDEX IF NOT EXISTS idx_chunk_src ON chunks(source_file);
    CREATE INDEX IF NOT EXISTS idx_books_topic ON books(topic);
    CREATE INDEX IF NOT EXISTS idx_rev_qid ON reviews(qid);
    """)
    c.execute(f"""CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks
                  USING vec0(embedding float[{config.EMBED_DIM}], chunk_id integer)""")
    c.commit(); c.close()

# ── questions ────────────────────────────────────────────────────────────
def add_question(topic, source_file, question, opts, correct, explanation, difficulty="intermediate"):
    c = connect()
    cur = c.execute(
        "INSERT INTO questions(topic,source_file,question,opt_a,opt_b,opt_c,opt_d,correct,explanation,difficulty,created)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (topic, source_file, question, opts[0], opts[1], opts[2], opts[3],
         correct, explanation, difficulty, datetime.datetime.utcnow().isoformat()))
    qid = cur.lastrowid
    c.execute("INSERT INTO sr_state(qid,ease,interval_days,reps,due) VALUES(?,?,?,?,?)",
              (qid, config.SM2_EASE0, 0, 0, datetime.date.today().isoformat()))
    c.commit(); c.close()
    return qid

def get_question(qid):
    c = connect(); r = c.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone(); c.close()
    return dict(r) if r else None

# ── spaced repetition (SM-2) ─────────────────────────────────────────────
def get_due_qids(limit=10, exclude=(), topic=None, mode=None):
    """Due question ids, optionally filtered by topic and/or mode.
    mode: None (any) | 'new' (never reviewed, reps=0) | 'hard' (≥1 wrong review)."""
    today = datetime.date.today().isoformat()
    sql = "SELECT s.qid FROM sr_state s JOIN questions q ON q.id=s.qid WHERE s.due<=?"
    args = [today]
    if topic:
        sql += " AND LOWER(q.topic) LIKE ?"
        args.append(f"%{topic.lower()}%")
    if mode == "new":
        sql += " AND s.reps=0"
    elif mode == "hard":
        sql += " AND EXISTS (SELECT 1 FROM reviews r WHERE r.qid=s.qid AND r.correct=0)"
    if exclude:
        ph = ",".join("?" * len(exclude))
        sql += f" AND s.qid NOT IN ({ph})"
        args += list(exclude)
    sql += " ORDER BY s.due LIMIT ?"
    args.append(limit)
    c = connect()
    rows = c.execute(sql, args).fetchall()
    c.close()
    return [r["qid"] for r in rows]

def log_review(qid, given, correct, latency_s, session_id):
    c = connect()
    c.execute("INSERT INTO reviews(qid,ts,given,correct,latency_s,session_id) VALUES(?,?,?,?,?,?)",
              (qid, datetime.datetime.utcnow().isoformat(), given, int(correct), latency_s, session_id))
    c.commit(); c.close()

def get_sr(qid):
    c = connect(); r = c.execute("SELECT * FROM sr_state WHERE qid=?", (qid,)).fetchone(); c.close()
    return dict(r) if r else None

def put_sr(qid, ease, interval_days, reps, due):
    c = connect()
    c.execute("UPDATE sr_state SET ease=?,interval_days=?,reps=?,due=?,last_reviewed=? WHERE qid=?",
              (ease, interval_days, reps, due, datetime.datetime.utcnow().isoformat(), qid))
    c.commit(); c.close()

# ── chunks + vectors ─────────────────────────────────────────────────────
def add_chunk(source_file, heading, ordinal, text, embedding):
    c = connect()
    cur = c.execute("INSERT INTO chunks(source_file,heading,ordinal,text) VALUES(?,?,?,?)",
                    (source_file, heading, ordinal, text))
    cid = cur.lastrowid
    c.execute("INSERT INTO vec_chunks(embedding,chunk_id) VALUES(?,?)", (_pack(embedding), cid))
    c.commit(); c.close()
    return cid

def chunks_for_source(source_file):
    c = connect()
    rows = c.execute("SELECT id,text FROM chunks WHERE source_file=? ORDER BY ordinal", (source_file,)).fetchall()
    c.close()
    return rows

def search_chunks(query_vec, k=None, source_file=None, source_files=None):
    """Cosine search via sqlite-vec. Scope to one source_file, a list of them,
    or all books (None)."""
    k = k or config.TOP_K
    qv = _pack(query_vec)
    c = connect()
    where = "WHERE v.embedding MATCH ? AND k=?"
    args = [qv, k]
    if source_files:
        ph = ",".join("?" * len(source_files))
        where += f" AND c.source_file IN ({ph})"
        args += list(source_files)
    elif source_file:
        where += " AND c.source_file=?"
        args.append(source_file)
    rows = c.execute(
        "SELECT c.id,c.source_file,c.heading,c.text,v.distance "
        "FROM vec_chunks v JOIN chunks c ON c.id=v.chunk_id "
        + where + " ORDER BY v.distance",
        args).fetchall()
    c.close()
    return [dict(r) for r in rows]


def source_files_for_topic(topic):
    """source_files registered for a topic (from the `books` table). Includes
    chunked-but-no-question books (e.g. a module handbook), so a teach session
    scoped to the topic can retrieve from them too."""
    c = connect()
    rows = c.execute("SELECT source_file FROM books WHERE LOWER(topic) LIKE ?",
                     (f"%{topic.lower()}%",)).fetchall()
    c.close()
    return [r[0] for r in rows]


def set_book(source_file, topic, path=""):
    """Register a book's topic (from its folder). Idempotent."""
    c = connect()
    c.execute("INSERT OR REPLACE INTO books(source_file,topic,path,ingested) VALUES(?,?,?,?)",
              (source_file, topic, path, datetime.datetime.utcnow().isoformat()))
    c.commit(); c.close()

def meta_get(k, default=None):
    c = connect(); r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone(); c.close()
    return r["v"] if r else default

def meta_set(k, v):
    c = connect(); c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v))); c.commit(); c.close()

if __name__ == "__main__":
    init_db()
    print("db ready:", config.DB_PATH)
