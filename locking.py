"""Process locks released by the OS when a caller crashes; lock files remain as stable inodes."""
from contextlib import contextmanager
import os


@contextmanager
def file_lock(path):
    with open(path,'a+b') as stream:
        stream.seek(0,os.SEEK_END)
        if not stream.tell():
            stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                raise BlockingIOError('Resource is locked by another process') from None
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream,fcntl.LOCK_UN)
