"""Cross-session run tracking and locking for a project's agent runs.

Two browser sessions (two tabs, two users) can both be looking at the same
project, so "is a run in progress" cannot live on ``rx.State`` — it has to
live on disk, in ``projects/<name>/.groundhog/``, where the runner itself
enforces it rather than the UI merely displaying it.

Layout::

    projects/<name>/.groundhog/
      lock.json        # present only while a run is active
      runs.jsonl        # one JSON object per *finished* run
      runs/<run_id>.log  # streamed stdout+stderr for that run

Locking is atomic (``O_EXCL``), not check-then-write, since that's the actual
mechanism that prevents two sessions from both starting a run for the same
project. The in-process registry used for cancellation is module-level state,
deliberately kept outside any ``rx.State`` so any session can reach it.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import fs

# A lock whose owning pid is alive but which is older than this is reclaimed
# anyway — a backstop for a process that died without a chance to clean up
# and got its pid reused, on top of the pid-liveness check that normally
# catches a dead owner immediately.
MAX_LOCK_AGE_SECONDS = 6 * 60 * 60


class AlreadyRunningError(Exception):
    """Raised by :func:`acquire` when another run already holds the lock."""

    def __init__(self, lock: "RunLock"):
        self.lock = lock
        super().__init__(
            f"{lock.kind} already running (provider={lock.provider}, "
            f"started {lock.started_at})"
        )


@dataclass(frozen=True)
class RunLock:
    run_id: str
    kind: str
    provider: str
    pid: int
    started_at: str  # ISO 8601 UTC

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "provider": self.provider,
            "pid": self.pid,
            "started_at": self.started_at,
        }

    @classmethod
    def from_json(cls, data: dict) -> "RunLock":
        return cls(
            run_id=data["run_id"],
            kind=data["kind"],
            provider=data["provider"],
            pid=data["pid"],
            started_at=data["started_at"],
        )


@dataclass
class _Handle:
    run_id: str
    proc: asyncio.subprocess.Process
    stop_requested: asyncio.Event


# resolved project directory -> handle for a subprocess spawned by *this*
# process. Deliberately module-level rather than on any rx.State: any
# session's "Stop" click has to be able to reach a run started by a different
# session. Keyed by the resolved directory rather than the bare project name
# so that distinct projects roots (as in tests, each pointed at its own
# tmp_path) can never collide on the same name.
_RUNNING: dict[str, _Handle] = {}


def _registry_key(project: str) -> str:
    return str(fs.project_dir(project).resolve())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _groundhog_dir(project: str) -> Path:
    d = fs.project_dir(project) / ".groundhog"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path(project: str) -> Path:
    return _groundhog_dir(project) / "lock.json"


def _runs_path(project: str) -> Path:
    return _groundhog_dir(project) / "runs.jsonl"


def _runs_dir(project: str) -> Path:
    d = _groundhog_dir(project) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path(project: str, run_id: str) -> Path:
    return _runs_dir(project) / f"{run_id}.log"


def ensure_layout(project: str) -> None:
    """Create ``.groundhog/`` (and an empty ``runs.jsonl``) for a project that
    predates this module, so `ls` shows the same layout as one created after
    it. Purely cosmetic/pre-seeding — every function above already creates
    whatever it needs lazily, so this is never required for correctness."""
    _runs_dir(project)
    path = _runs_path(project)
    if not path.exists():
        path.touch()


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, just owned by someone else — still alive.
        return True
    return True


def _age_seconds(started_at: str) -> float:
    started = datetime.fromisoformat(started_at)
    return (datetime.now(timezone.utc) - started).total_seconds()


def _is_stale(lock: RunLock) -> bool:
    return not _is_alive(lock.pid) or _age_seconds(lock.started_at) > MAX_LOCK_AGE_SECONDS


def current(project: str) -> RunLock | None:
    """Return the active lock, reclaiming (and clearing) it first if stale."""
    path = _lock_path(project)
    if not path.is_file():
        return None
    try:
        lock = RunLock.from_json(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, OSError):
        # An unreadable lock file can't be trusted to represent a live run.
        path.unlink(missing_ok=True)
        return None
    if _is_stale(lock):
        _reclaim_stale(project, lock)
        return None
    return lock


def _reclaim_stale(project: str, lock: RunLock) -> None:
    append_record(
        project,
        {
            "run_id": lock.run_id,
            "kind": lock.kind,
            "provider": lock.provider,
            "started_at": lock.started_at,
            "ended_at": _now(),
            "exit_code": None,
            "status": "stale",
            "log_file": f"runs/{lock.run_id}.log",
        },
    )
    _lock_path(project).unlink(missing_ok=True)


def acquire(project: str, kind: str, provider: str) -> RunLock:
    """Atomically take the lock for ``project``, reclaiming a stale one first.

    Raises :class:`AlreadyRunningError` if another run genuinely holds it.
    """
    lock = RunLock(
        run_id=uuid.uuid4().hex,
        kind=kind,
        provider=provider,
        pid=os.getpid(),
        started_at=_now(),
    )
    path = _lock_path(project)
    if _try_create(path, lock):
        return lock

    existing = current(project)  # clears it first if stale, returns None if so
    if existing is None:
        # The lock we lost the race against was stale and current() already
        # removed it — retry the atomic create once.
        if _try_create(path, lock):
            return lock
        # Someone else won the retry in the meantime.
        existing = current(project)

    if existing is not None:
        raise AlreadyRunningError(existing)
    raise AlreadyRunningError(lock)  # pragma: no cover - extremely unlikely race


def _try_create(path: Path, lock: RunLock) -> bool:
    """Atomically create ``path`` with ``lock``'s content, or fail if it
    already exists.

    Written via a temp file + ``os.link`` rather than
    ``O_CREAT | O_EXCL`` directly on ``path``: the latter makes the file
    exist-but-empty for the moment between creating it and writing its
    content, during which a concurrent reader (this function's own caller,
    from another thread/process racing to acquire the same lock) can observe
    an empty/corrupt file, conclude it's unreadable, delete it, and create its
    own — two winners. Linking a fully-written temp file into place means the
    path never appears in a half-written state.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(lock.to_json()))
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def update_pid(project: str, run_id: str, pid: int) -> None:
    """Point the lock at the actual agent subprocess pid once it's spawned.

    Safe as a plain (non-atomic) overwrite: only the session that created the
    lock ever calls this, so there is no concurrent writer to race with.
    """
    path = _lock_path(project)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if data.get("run_id") != run_id:
        return
    data["pid"] = pid
    path.write_text(json.dumps(data))


def release(project: str, run_id: str) -> None:
    """Remove the lock, but only if it's still the one we created."""
    path = _lock_path(project)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if data.get("run_id") == run_id:
        path.unlink(missing_ok=True)


def append_record(project: str, record: dict) -> None:
    path = _runs_path(project)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def find_record(project: str, run_id: str) -> dict | None:
    """Look up a finished run's record by id, e.g. to report its outcome to a
    session that was only watching it, not the one that started it."""
    path = _runs_path(project)
    if not path.is_file():
        return None
    match = None
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("run_id") == run_id:
            match = record
    return match


def append_log_line(project: str, run_id: str, line: str) -> None:
    with log_path(project, run_id).open("a") as f:
        f.write(line + "\n")


def tail_log(project: str, run_id: str, offset: int = 0) -> tuple[list[str], int]:
    """Read new lines written since ``offset`` bytes into the run's log file.

    Returns ``(new_lines, new_offset)`` so a caller can poll incrementally.
    """
    path = log_path(project, run_id)
    if not path.is_file():
        return [], offset
    with path.open("r") as f:
        f.seek(offset)
        text = f.read()
        new_offset = f.tell()
    lines = text.splitlines()
    return lines, new_offset


def register_process(project: str, run_id: str, proc: asyncio.subprocess.Process) -> None:
    _RUNNING[_registry_key(project)] = _Handle(
        run_id=run_id, proc=proc, stop_requested=asyncio.Event()
    )


def unregister_process(project: str) -> None:
    _RUNNING.pop(_registry_key(project), None)


def stop_requested(project: str) -> bool:
    handle = _RUNNING.get(_registry_key(project))
    return handle is not None and handle.stop_requested.is_set()


def request_stop(project: str) -> bool:
    """Ask the run for ``project`` to stop. Returns False if nothing is running."""
    handle = _RUNNING.get(_registry_key(project))
    if handle is not None:
        handle.stop_requested.set()
        if handle.proc.returncode is None:
            handle.proc.terminate()
        return True

    lock = current(project)
    if lock is None:
        return False
    if _is_alive(lock.pid):
        try:
            os.kill(lock.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        return True
    return False
