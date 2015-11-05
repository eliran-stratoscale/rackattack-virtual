import os
import errno


def _mkdirWithParents(path):
    if os.path.exists(path):
        return
    try:
        os.makedirs(path)
    except OSError as ex:
        if ex.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


def validateFifoExists(path):
    dirname = os.path.dirname(path)
    if not os.path.exists(dirname):
        _mkdirWithParents(dirname)
    if not os.path.exists(path):
        try:
            os.mkfifo(path)
        except Exception as ex:
            if ex.errno == errno.EEXIST and os.path.exists(path):
                pass
            else:
                raise
