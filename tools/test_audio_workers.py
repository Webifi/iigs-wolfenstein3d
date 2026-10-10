"""Nested fitting shares the song budget and releases slots on failure."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from audio_workers import Permit,permit,map_fits


class WorkerTests(unittest.TestCase):
    def run_pool(self,busy=False,fail=False):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,WOLF_AUDIO_POOL=root,WOLF_AUDIO_WORKERS='3'):
            mutex=threading.Lock();counts=[0,0]
            def one(value):
                with mutex:
                    counts[0]+=1;counts[1]=max(counts)
                try:
                    time.sleep(.002)
                    if fail and value==2:raise ValueError('fit failed')
                    return value*value
                finally:
                    with mutex:counts[0]-=1
            with permit():
                reserved=[]
                if busy:
                    for _ in range(2):
                        token=Permit();self.assertTrue(token.try_acquire());reserved.append(token)
                try:
                    if fail:
                        with self.assertRaises(ValueError):map_fits(one,list(range(8)))
                    else:
                        got=map_fits(lambda value:map_fits(one,[value,value+1]),list(range(8)))
                        self.assertEqual(got,[[v*v,(v+1)*(v+1)] for v in range(8)])
                        self.assertLessEqual(counts[1],1 if busy else 3)
                finally:
                    for token in reserved:token.release()
            tokens=[Permit() for _ in range(4)]
            try:
                self.assertEqual([token.try_acquire() for token in tokens],[True,True,True,False])
            finally:
                for token in tokens:token.release()

    def test_nested_order_and_budget(self):self.run_pool()
    def test_occupied_slots_stay_serial(self):self.run_pool(busy=True)
    def test_failed_fit_releases_slots(self):self.run_pool(fail=True)


if __name__=='__main__':unittest.main()
