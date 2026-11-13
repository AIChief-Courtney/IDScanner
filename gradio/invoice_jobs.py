"""Short-lived server-side job state; unreleased results never enter UI outputs."""
import secrets
import threading
import time
from dataclasses import dataclass, field


@dataclass
class InvoiceJob:
    created: float = field(default_factory=time.monotonic)
    file_key: str | None = None
    confirmed: bool = False
    confirmed_at: float | None = None
    confirmation_version: int = 0
    verification_phase: str = 'preparing'
    phase_until: float = 0
    progress_started: float | None = None
    progress_duration: float = 60
    display_percent: int = 0
    cancelled: bool = False
    worker: threading.Thread | None = None
    started: float | None = None
    finished: float | None = None
    running: bool = False
    failed: bool = False
    percent: int = 0
    status: str = ''
    preview: str = ''
    result: dict | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)


_jobs = {}
_lock = threading.Lock()


def create_job(file_key=None):
    now = time.monotonic()
    with _lock:
        expired = [key for key, job in _jobs.items() if not job.running and now - job.created > 1800]
        for key in expired:
            del _jobs[key]
        key = secrets.token_urlsafe(24)
        _jobs[key] = InvoiceJob(created=now, file_key=file_key, phase_until=now + 5)
        return key


def get_job(key):
    with _lock:
        job = _jobs.get(key)
        if job is not None and not job.running and time.monotonic() - job.created > 1800:
            del _jobs[key]
            return None
        return job


def advance_verification(job, now):
    if job.verification_phase == 'preparing' and now >= job.phase_until:
        job.verification_phase = 'awaiting'
    elif job.verification_phase == 'confirming' and now >= job.phase_until:
        job.verification_phase = 'verified'
        job.confirmed = True
        job.confirmed_at = job.phase_until
        job.progress_started = now
        elapsed = now - job.started if job.started is not None else 0
        job.progress_duration = max(1, 60 - elapsed)
