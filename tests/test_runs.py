"""Locking and run-history primitives in groundhog.lib.runs (cross-session fix)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from groundhog.lib import fs, runs


@pytest.fixture
def proj(sandbox):
    return fs.create_project("Locking")


# --- acquire / release --------------------------------------------------


def test_acquire_creates_lock_file_with_expected_fields(proj):
    lock = runs.acquire(proj, "experiment", "claude_code")
    data = json.loads((fs.project_dir(proj) / ".groundhog" / "lock.json").read_text())
    assert data["run_id"] == lock.run_id
    assert data["kind"] == "experiment"
    assert data["provider"] == "claude_code"
    assert data["pid"] == os.getpid()
    assert data["started_at"]


def test_acquire_while_locked_raises_already_running(proj):
    runs.acquire(proj, "experiment", "claude_code")
    with pytest.raises(runs.AlreadyRunningError):
        runs.acquire(proj, "experiment", "claude_code")


def test_release_removes_the_lock_file(proj):
    lock = runs.acquire(proj, "experiment", "claude_code")
    runs.release(proj, lock.run_id)
    assert runs.current(proj) is None


def test_release_with_stale_run_id_is_a_no_op(proj):
    lock = runs.acquire(proj, "experiment", "claude_code")
    runs.release(proj, "not-the-run-id")
    assert runs.current(proj) is not None
    runs.release(proj, lock.run_id)


def test_current_returns_none_when_no_lock(proj):
    assert runs.current(proj) is None


def test_current_returns_the_active_lock(proj):
    lock = runs.acquire(proj, "analysis", "claude_code")
    assert runs.current(proj) == lock


# --- staleness -----------------------------------------------------------


def test_stale_lock_with_dead_pid_is_reclaimed(proj):
    # A real process that has already exited by the time we check it.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    dead_pid = proc.pid

    lock_path = fs.project_dir(proj) / ".groundhog" / "lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "run_id": "dead-run",
                "kind": "experiment",
                "provider": "claude_code",
                "pid": dead_pid,
                "started_at": runs._now(),
            }
        )
    )

    assert runs.current(proj) is None
    assert not lock_path.is_file()
    records = [
        json.loads(line)
        for line in (fs.project_dir(proj) / ".groundhog" / "runs.jsonl").read_text().splitlines()
    ]
    assert records[0]["run_id"] == "dead-run"
    assert records[0]["status"] == "stale"


def test_stale_lock_past_max_age_is_reclaimed_even_if_pid_alive(proj, monkeypatch):
    monkeypatch.setattr(runs, "MAX_LOCK_AGE_SECONDS", 0)
    runs.acquire(proj, "experiment", "claude_code")
    assert runs.current(proj) is None


def test_acquiring_after_a_stale_lock_succeeds(proj, monkeypatch):
    monkeypatch.setattr(runs, "MAX_LOCK_AGE_SECONDS", 0)
    first = runs.acquire(proj, "experiment", "claude_code")
    # Acquiring again doesn't raise AlreadyRunningError, because the first
    # lock is immediately stale under a zero max age.
    second = runs.acquire(proj, "experiment", "claude_code")
    assert second.run_id != first.run_id
    records = [
        json.loads(line)
        for line in (fs.project_dir(proj) / ".groundhog" / "runs.jsonl").read_text().splitlines()
    ]
    assert records[0]["run_id"] == first.run_id
    assert records[0]["status"] == "stale"


# --- run history -----------------------------------------------------------


def test_append_record_writes_one_json_line_per_call(proj):
    runs.append_record(proj, {"run_id": "a", "status": "completed"})
    runs.append_record(proj, {"run_id": "b", "status": "failed"})
    lines = (fs.project_dir(proj) / ".groundhog" / "runs.jsonl").read_text().splitlines()
    assert [json.loads(l)["run_id"] for l in lines] == ["a", "b"]


# --- log tailing -----------------------------------------------------------


def test_tail_log_returns_new_lines_since_offset(proj):
    runs.append_log_line(proj, "run1", "line one")
    lines, offset = runs.tail_log(proj, "run1", 0)
    assert lines == ["line one"]

    runs.append_log_line(proj, "run1", "line two")
    lines, offset2 = runs.tail_log(proj, "run1", offset)
    assert lines == ["line two"]
    assert offset2 > offset


def test_tail_log_missing_file_returns_empty(proj):
    assert runs.tail_log(proj, "no-such-run", 0) == ([], 0)


# --- stop / registry ---------------------------------------------------


def test_request_stop_returns_false_when_nothing_running(proj):
    assert runs.request_stop(proj) is False


async def test_request_stop_terminates_registered_process(proj):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)"
    )
    runs.register_process(proj, "run1", proc)
    try:
        assert runs.request_stop(proj) is True
        assert runs.stop_requested(proj) is True
        await asyncio.wait_for(proc.wait(), timeout=5)
        assert proc.returncode is not None
    finally:
        runs.unregister_process(proj)
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


def test_request_stop_falls_back_to_pid_when_not_registered_in_process(proj):
    """Simulates a run owned by a different worker process: nothing in the
    in-process registry, but a lock file naming a live pid on this host."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock_path = fs.project_dir(proj) / ".groundhog" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(
                {
                    "run_id": "other-worker-run",
                    "kind": "experiment",
                    "provider": "claude_code",
                    "pid": proc.pid,
                    "started_at": runs._now(),
                }
            )
        )
        assert runs.request_stop(proj) is True
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# --- the actual regression: concurrent acquisition has exactly one winner --


async def test_concurrent_acquire_only_one_winner(proj):
    results = await asyncio.gather(
        *[
            asyncio.to_thread(runs.acquire, proj, "experiment", "claude_code")
            for _ in range(8)
        ],
        return_exceptions=True,
    )
    winners = [r for r in results if isinstance(r, runs.RunLock)]
    losers = [r for r in results if isinstance(r, runs.AlreadyRunningError)]
    assert len(winners) == 1
    assert len(losers) == 7
