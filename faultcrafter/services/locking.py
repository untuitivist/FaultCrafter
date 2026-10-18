from __future__ import annotations

from pathlib import Path
import sys
import threading


class ComputeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._thread_lock = threading.Lock()
        self._stream = None

    def __enter__(self) -> ComputeLock:
        self._thread_lock.acquire()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = self.path.open("a+b")
            self._stream = stream
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException as error:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._thread_lock.release()
            if isinstance(error, OSError):
                raise RuntimeError("同一用户目录已有训练或生成进程占用计算资源") from error
            raise
        return self

    def __exit__(self, *exception: object) -> None:
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            self._thread_lock.release()
