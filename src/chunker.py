import os, glob, json, urllib.request
from . import config, db

CHUNK_CHARS = config.CHUNK_TOKENS * 4          # ~500 tokens -> ~2000 chars
OVERLAP_CHARS = config.CHUNK_OVERLAP * 4

def _split_section(heading, body):
    """Yield (heading, ordinal, text) chunks from one section's body."""
    paras = [p for p in body.split("\n\n") if p.strip()]
    buf, start = 0, 0
    acc = []
    ordn = 0
    for p in paras:
        acc.append(p)
        buf += len(p) + 2
        if buf >= CHUNK_CHARS:
            text = "\n\n".join(acc).strip()
            if text:
                yield heading, ordn, text
                ordn += 1
            # overlap: carry the last paragraph forward
            if len(acc) > 1 and len(acc[-1]) < OVERLAP_CHARS:
                acc = [acc[-1]]
            else:
                acc = []
            buf = len(acc[0]) + 2 if acc else 0
    text = "\n\n".join(acc).strip()
    if text:
        yield heading, ordn, text

def chunk_text(md):
    """Split markdown into (heading, ordinal, text) chunks, section by heading."""
    sections = []           # list of (heading, body)
    cur_h, cur_body = "(intro)", []
    for line in md.split("\n"):
        if line.lstrip().startswith("#"):
            sections.append((cur_h, "\n".join(cur_body)))
            cur_h = line.lstrip("# ").strip() or cur_h
            cur_body = []
        else:
            cur_body.append(line)
    sections.append((cur_h, "\n".join(cur_body)))
    for heading, body in sections:
        if not body.strip():
            continue
        yield from _split_section(heading, body)

def embed(text):
    """Embed via Ollama. Returns list[float]. Needs Ollama running.
    Current API: POST /api/embed {model, input} -> {embeddings: [[...]]}
    Fallback (older Ollama): POST /api/embeddings {model, prompt} -> {embedding: [...]}
    """
    import urllib.error
    base = config.OLLAMA_HOST.rstrip("/")
    payload = json.dumps({"model": config.EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(base + "/api/embed",
                                 data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["embeddings"][0]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # older Ollama only had /api/embeddings
        payload2 = json.dumps({"model": config.EMBED_MODEL, "prompt": text}).encode()
        req2 = urllib.request.Request(base + "/api/embeddings",
                                      data=payload2, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2, timeout=60) as r:
            return json.load(r)["embedding"]

def _source_name(path):
    return os.path.basename(path)

def already_embedded(path):
    src = _source_name(path)
    c = db.connect()
    n = c.execute("SELECT COUNT(*) FROM chunks WHERE source_file=?", (src,)).fetchone()[0]
    c.close()
    return n > 0

def embed_book(path):
    src = _source_name(path)
    if already_embedded(path):
        print(f"skip (already chunked): {src}")
        return 0
    md = open(path, encoding="utf-8", errors="replace").read()
    n = 0
    for heading, ordn, text in chunk_text(md):
        if len(text) < 40:
            continue
        try:
            vec = embed(text)
        except Exception as e:
            print(f"  embed error chunk {n} ({heading}): {e} - aborting {src}")
            return n
        db.add_chunk(src, heading, ordn, text, vec)
        n += 1
        if n % 25 == 0:
            print(f"  {src}: {n} chunks")
    print(f"embedded {src}: {n} chunks")
    return n

def embed_all():
    """Chunk + embed every .md in config.TEXT_DIR."""
    paths = sorted(glob.glob(os.path.join(config.TEXT_DIR, "*.md")))
    print(f"found {len(paths)} markdown files in {config.TEXT_DIR}")
    total = 0
    for p in paths:
        total += embed_book(p)
    print(f"done. {total} chunks added this run.")

if __name__ == "__main__":
    embed_all()
