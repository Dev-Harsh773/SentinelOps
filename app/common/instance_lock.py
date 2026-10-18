"""OS-held lock enforcing single-process ownership of a production volume."""
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.file = open(Path(directory) / ".instance.lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.write(b"0")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another SentinelOps process owns this runtime volume") from None

    def close(self):
        self.file.close()
