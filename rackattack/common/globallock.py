import threading
import contextlib
import time
import traceback
import logging


_lock = threading.Lock()


def prettyStack():
    return "\n".join([line.strip() for line in traceback.format_stack()])


@contextlib.contextmanager
def lock():
    before = time.time()
    with _lock:
        acquired = time.time()
        took = acquired - before
        if took > 0.1:
            logging.error(
                "Acquiring the global lock took more than 0.1s: %(took)ss. Stack:\n%(stack)s", dict(
                    took=took, stack=prettyStack()))
        yield
        released = time.time()
        took = released - acquired
        if took > 0.3:
            logging.error(
                "Holding the global lock took more than 0.1s: %(took)ss. Stack:\n%(stack)s", dict(
                    took=took, stack=prettyStack()))


def assertLocked():
    assert not _lock.acquire(False)
    return True
