"""Load / advance / save a user's cooker safely.

``open_cooker`` is the only door to a cooker's state. It
  1. takes an in-process lock for that cooker (so a phone and a laptop polling at
     the same time cannot both advance and overwrite each other),
  2. opens a transaction with ``select_for_update`` (the same guarantee across
     several worker processes on PostgreSQL),
  3. replays the elapsed real time, lets the caller read/command the simulator,
  4. saves the new state if anything changed.
"""
import threading
from contextlib import contextmanager

from django.db import transaction

from .models import Cooker
from .simulator import SmartCooker

_locks = {}
_guard = threading.Lock()


def _lock_for(pk):
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


@contextmanager
def open_cooker(user, pk):
    """Yield a Handle for ``user``'s cooker ``pk``. Raises Cooker.DoesNotExist if not theirs."""
    with _lock_for(pk):
        with transaction.atomic():
            obj = Cooker.objects.select_for_update().get(pk=pk, owner=user)
            sim = SmartCooker.from_dict(obj.state_data)
            handle = Handle(obj, sim, sim.advance())
            yield handle
            if handle.dirty:
                obj.state_data = sim.to_dict()
                obj.save(update_fields=["state_data", "updated_at"])


def new_state():
    return SmartCooker().to_dict()
