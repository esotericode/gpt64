"""Append-only, searchable public notes, shared across runs and providers."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading

MAX_NOTE = 2000
MAX_QUERY = 200
_THREAD_LOCK = threading.RLock()


class Scratchpad:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "notes.jsonl"

    @contextmanager
    def locked(self):
        # Avoid mandatory Windows byte-range locks colliding with other local
        # threads, and never rewrite byte 0 while another process owns it.
        with _THREAD_LOCK:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / "write.lock").open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0"); handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def _entries(self):
        if not self.path.exists():
            return []
        entries = []
        with self.path.open(encoding="utf-8") as source:
            for line in source:
                try:
                    entry = json.loads(line)
                    if (not isinstance(entry, dict) or not isinstance(entry.get("text"), str) or not 1 <= len(entry["text"]) <= MAX_NOTE
                            or not isinstance(entry.get("id"), str) or not isinstance(entry.get("time"), str)):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError("Scratchpad contains a damaged record. Back up notes.jsonl before repairing it; earlier notes have not been erased.") from None
                entries.append(entry)
        return entries

    def append(self, text, *, key=None, run_id=None, model=None):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_NOTE:
            raise ValueError("Scratchpad notes must be 1–2000 characters")
        text = text.strip()
        note_id = hashlib.sha256((key or text).encode()).hexdigest()[:32]
        with self.locked():
            # Read under the same OS lock as writers; never erase/correct old notes.
            entries = self._entries()
            for entry in entries:
                if entry["id"] == note_id:
                    if entry["text"] != text:
                        raise ValueError("This scratchpad write ID already contains a different note")
                    return entry
            entry = {"id": note_id, "time": datetime.now(timezone.utc).isoformat(),
                     "text": text, "run_id": run_id, "model": model}
            with self.path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(entry, ensure_ascii=False) + "\n")
                target.flush(); os.fsync(target.fileno())
            return entry

    def context(self, query="", offset=0, max_chars=12000):
        if not isinstance(query, str) or len(query) > MAX_QUERY:
            raise ValueError("Scratchpad search must be at most 200 characters")
        if type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError("Scratchpad offset must be an integer from 0 to 1000000")
        with self.locked():
            entries = self._entries()
        terms = re.findall(r"\w+", query.casefold())[:12]
        # Always keep recent corrections alongside recalled older entries.
        selected = set(range(max(0, len(entries) - 6), len(entries)))
        if terms:
            ranked = sorted(((sum(term in entry["text"].casefold() for term in terms), i)
                             for i, entry in enumerate(entries)), reverse=True)
            candidates = [i for score, i in ranked if score]
        else:
            candidates = list(range(len(entries) - 1, -1, -1))
        # Five recalled entries plus the latest correction fit even if each
        # entry has the maximum length. Paging never skips an unseen entry.
        page = candidates[offset:offset + 5]
        recalled = set(page)
        selected.update(recalled)
        result, used = [], 0
        newest = len(entries) - 1
        for i in sorted(selected, key=lambda i: (i == newest, i in recalled, i), reverse=True):
            entry = entries[i]
            if used + len(entry["text"]) <= max_chars:
                result.append(entry); used += len(entry["text"])
        result.sort(key=lambda entry: entry["time"])
        next_offset = offset + len(page) if offset + len(page) < len(candidates) else None
        return {"entries": result, "total_notes": len(entries), "query": query, "offset": offset,
                "next_offset": next_offset, "has_more": next_offset is not None}

    def export(self):
        with self.locked():
            self._entries()  # Report corruption rather than silently dropping notes.
            return self.path.read_bytes() if self.path.exists() else b""
