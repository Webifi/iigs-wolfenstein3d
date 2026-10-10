"""One CPU budget shared by song processes and independent instrument fits."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import threading
import time

_local=threading.local()


class Permit:
    def __init__(self):self.file=None
    def try_acquire(self):
        root=os.environ.get('WOLF_AUDIO_POOL')
        if not root:return True
        count=int(os.environ.get('WOLF_AUDIO_WORKERS','1'))
        for index in range(count):
            handle=(Path(root)/str(index)).open('a+b')
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:handle.close()
            else:
                self.file=handle
                return True
        return False
    def acquire(self):
        while not self.try_acquire():time.sleep(.01)
    def release(self):
        if self.file is not None:
            self.file.close();self.file=None


@contextmanager
def permit():
    token=Permit();token.acquire();_local.token=token
    try:yield
    finally:token.release();_local.token=None


def map_fits(function,items):
    jobs=int(os.environ.get('WOLF_AUDIO_WORKERS','1')) if os.environ.get('WOLF_AUDIO_POOL') else 1
    if jobs<=1 or len(items)<2 or getattr(_local,'mapped',False):
        return [function(item) for item in items]
    token=getattr(_local,'token',None)
    if token is None:
        with permit():return map_fits(function,items)
    # Busy song workers keep their slots. Only idle slots become fit workers;
    # nested fits must not create polling threads waiting for their parents.
    extra=[]
    for _ in range(min(jobs,len(items))-1):
        spare=Permit()
        if not spare.try_acquire():break
        extra.append(spare)
    if not extra:return [function(item) for item in items]
    from concurrent.futures import ThreadPoolExecutor
    pending=iter(enumerate(items));result=[None]*len(items)
    def work():
        _local.mapped=True
        try:
            for index,item in pending:result[index]=function(item)
        finally:_local.mapped=False
    try:
        with ThreadPoolExecutor(max_workers=1+len(extra)) as pool:
            futures=[pool.submit(work) for _ in range(1+len(extra))]
            for future in futures:future.result()
        return result
    finally:
        for spare in extra:spare.release()
