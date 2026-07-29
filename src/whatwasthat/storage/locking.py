"""POSIX inter-process locks shared by local WWT writers and workers."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


class InterProcessLock:
    """Small ``flock`` wrapper with blocking and non-blocking acquisition."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[str] | None = None

    def acquire(self, *, blocking: bool = True) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("w")
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(lock_file, flags)
        except BlockingIOError:
            lock_file.close()
            return False
        self._file = lock_file
        return True

    def release(self) -> None:
        if self._file is None:
            return
        fcntl.flock(self._file, fcntl.LOCK_UN)
        self._file.close()
        self._file = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def __enter__(self) -> InterProcessLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


@contextmanager
def write_lock(data_dir: Path) -> Iterator[None]:
    """Serialize all mutations of the local Chroma/raw/BM25 stores."""
    with InterProcessLock(data_dir / "wwt.lock"):
        yield
