"""QuizBot SimpleX transport: own profile + pty + read-only DB poll.

Adapted from ./bridge.py (proven pty design).
One `simplex-chat -a` runs in a pty (sole client). Replies are typed into the
pty as `@<contact> <msg>\\n`. Inbound messages are read from the chat DB.
"""
import os, time, json, sqlite3, subprocess, select, fcntl, struct, termios, pty, signal, traceback, shutil
from . import config

PTY_LOG = os.path.join(config.STATE_DIR, "quizbot-pty.log")
LAST_ID_FILE = os.path.join(config.STATE_DIR, "last_id")
READY_MARKER = (b"Current user:", b"subscribed", b"your profile")

def _log(msg):
    line = f"[{time.strftime('%F %T')}] {msg}"
    os.makedirs(config.STATE_DIR, exist_ok=True)
    try:
        with open(os.path.join(config.STATE_DIR, "quizbot.log"), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(f"[quizbot] {msg}", flush=True)


class QuizBot:
    def __init__(self):
        os.makedirs(config.STATE_DIR, exist_ok=True)
        os.makedirs(config.QUIZBOT_FILES, exist_ok=True)
        self.proc = None
        self.master = None
        self.contact_id = None
        self.contact_name = None

    # ── read-only DB helpers ────────────────────────────────────────────
    def db_query(self, sql, args=()):
        conn = sqlite3.connect(f"file:{config.QUIZBOT_DB}?mode=ro", uri=True, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def resolve_contact(self):
        """Find the single non-user contact (the user's phone). Returns bool ok."""
        rows = self.db_query(
            "SELECT contact_id, local_display_name FROM contacts "
            "WHERE is_user=0 AND deleted=0 ORDER BY contact_id DESC")
        if not rows:
            return False
        # prefer a contact named exactly QUIZBOT_CONTACT, else the latest
        for r in rows:
            if (r["local_display_name"] or "") == config.QUIZBOT_CONTACT:
                self.contact_id, self.contact_name = r["contact_id"], r["local_display_name"]
                return True
        r = rows[0]
        self.contact_id, self.contact_name = r["contact_id"], r["local_display_name"] or "user"
        return True

    # ── pty management ───────────────────────────────────────────────────
    def _drain(self, t=0.2):
        if self.master is None:
            return
        end = time.time() + t
        try:
            with open(PTY_LOG, "ab") as f:
                while time.time() < end:
                    r, _, _ = select.select([self.master], [], [], 0.05)
                    if not r:
                        continue
                    try:
                        data = os.read(self.master, 65536)
                        if not data:
                            break
                        f.write(data)
                    except OSError:
                        break
        except Exception as e:
            _log(f"drain error: {e}")

    def _write(self, text):
        if self.master is None or (self.proc and self.proc.poll() is not None):
            _log("pty dead, restarting simplex-chat")
            if not self.start():
                return False
        try:
            os.write(self.master, text.encode())
            return True
        except OSError as e:
            _log(f"pty write error: {e}")
            return False

    def start(self):
        subprocess.run([shutil.which("pkill") or "pkill", "-f",
                        f"simplex-chat.*{config.QUIZBOT_DB_PREFIX}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        master, slave = pty.openpty()
        for _ in range(3):
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 120, 0, 0))
                break
            except OSError:
                time.sleep(0.2)
        cmd = [config.SIMPLEX_CHAT_BIN, "-y", "-a", "-d", config.QUIZBOT_DB_PREFIX,
               "--files-folder", config.QUIZBOT_FILES, "--mute"]
        _log(f"spawning {' '.join(cmd)}")
        try:
            self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave,
                                         start_new_session=True)
            os.close(slave)
        except Exception as e:
            _log(f"spawn failed: {e}")
            return False
        self.master = master
        # wait for readiness
        end = time.time() + 40
        while time.time() < end:
            if self.proc.poll() is not None:
                _log(f"simplex-chat exited rc={self.proc.returncode}")
                return False
            time.sleep(0.5)
            self._drain(0.05)
            try:
                with open(PTY_LOG, "rb") as f:
                    tail = f.read()[-4096:]
                if any(m in tail for m in READY_MARKER):
                    _log("simplex-chat ready")
                    return True
            except Exception:
                pass
        _log("simplex-chat NOT ready in 40s")
        return False

    # ── outbound ────────────────────────────────────────────────────────
    def send(self, msg):
        if not self.contact_id and not self.resolve_contact():
            _log("cannot send: no contact yet (user must scan the invite QR)")
            return False
        if len(msg) > config.MAX_REPLY_CHARS:
            msg = msg[:config.MAX_REPLY_CHARS] + " [...]"
        _log(f"SEND: {msg[:80]!r}")
        line = f"@{self.contact_name} {msg}\n"
        for _ in range(3):
            if self._write(line):
                time.sleep(0.4)
                self._drain(0.6)
                return True
            time.sleep(1)
        _log("SEND FAILED after 3 attempts")
        return False

    # ── inbound poll ────────────────────────────────────────────────────
    def _last_id(self):
        if os.path.exists(LAST_ID_FILE):
            try:
                return int(open(LAST_ID_FILE).read().strip() or "0")
            except ValueError:
                pass
        init = 0
        if self.contact_id:
            r = self.db_query(
                "SELECT COALESCE(MAX(chat_item_id),0) AS m FROM chat_items "
                "WHERE contact_id=? AND item_sent=0 AND item_deleted=0",
                (self.contact_id,))
            init = r[0]["m"] if r else 0
        with open(LAST_ID_FILE, "w") as f:
            f.write(str(init))
        _log(f"init last_id={init}")
        return init

    def new_messages(self):
        """Return list of (id, text) for inbound messages since last poll."""
        if not self.contact_id and not self.resolve_contact():
            return []
        last = self._last_id()
        rows = self.db_query(
            "SELECT chat_item_id, item_text FROM chat_items "
            "WHERE contact_id=? AND item_sent=0 AND item_deleted=0 AND chat_item_id>? "
            "ORDER BY chat_item_id ASC",
            (self.contact_id, last))
        out = []
        for r in rows:
            t = (r["item_text"] or "").strip()
            if t:
                out.append((r["chat_item_id"], t))
        if out:
            with open(LAST_ID_FILE, "w") as f:
                f.write(str(out[-1][0]))
        return out

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        _log("stopped")
