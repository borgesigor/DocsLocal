import os

from app.core.config import STATE


class InstanceLock:
    def __init__(self):
        self.lock_file = None

    def acquire(self):
        STATE.mkdir(parents=True, exist_ok=True)
        self.lock_file = (STATE / 'instance.lock').open('a+b')
        self.lock_file.seek(0, os.SEEK_END)
        if self.lock_file.tell() == 0:
            self.lock_file.write(b'0')
            self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError('Outra instância do Docs Local já está usando esta pasta de dados.')

    def release(self):
        if self.lock_file is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock_file.seek(0)
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self.lock_file.close()
            self.lock_file = None
