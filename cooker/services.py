"""Load / advance / save a user's cooker safely.

``open_cooker`` is the only door to a cooker's state. It
  1. takes an in-process lock for that cooker (so a phone and a laptop polling at
     the same time cannot both advance and overwrite each other),
  2. opens a transaction with ``select_for_update`` (the same guarantee across
     several worker processes on PostgreSQL),
  3. replays the elapsed real time, lets the caller read/command the simulator,
  4. books every cook that ended (cost at the REG tariff) and saves the new state if anything changed.
"""
import threading
from contextlib import contextmanager

from django.db import connection, transaction

from .models import Cooker
from .simulator import SmartCooker

_locks = {}
_guard = threading.Lock()


_sqlite_lock = threading.Lock()


def _lock_for(pk):
    # SQLite allows one writer at a time, so on SQLite every cooker shares ONE lock
    # (writes take milliseconds). Other databases lock per cooker (+ select_for_update).
    if connection.vendor == "sqlite":
        return _sqlite_lock
    with _guard:
        lock = _locks.get(pk)
        if lock is None:
            lock = _locks[pk] = threading.Lock()
        return lock


class Handle:
    def __init__(self, obj, sim, dirty):
        self.obj = obj
        self.sim = sim
        self.dirty = dirty      # set True after changing the simulator

    def settle(self):
        """Write cooks that have ended since the last call to the database, priced at the REG tariff."""
        cooks = self.sim.finished_cooks
        if not cooks:
            return
        from .tariff import record_cook

        for d in list(cooks):
            record_cook(self.obj, d)
        self.sim.finished_cooks = []
        self.dirty = True


@contextmanager
def open_cooker(user, pk):
    """Yield a Handle for ``user``'s cooker ``pk``. Raises Cooker.DoesNotExist if not theirs."""
    with _lock_for(pk):
        with transaction.atomic():
            obj = Cooker.objects.select_for_update().get(pk=pk, owner=user)
            sim = SmartCooker.from_dict(obj.state_data)
            handle = Handle(obj, sim, sim.advance())
            handle.settle()
            yield handle
            handle.settle()
            if handle.dirty:
                obj.state_data = sim.to_dict()
                obj.save(update_fields=["state_data", "updated_at"])


def new_state():
    return SmartCooker().to_dict()
