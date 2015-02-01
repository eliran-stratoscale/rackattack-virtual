from rackattack.virtual.alloc import allocation
from rackattack.common import globallock


class Allocations:
    def __init__(self, dnsmasq, broadcaster, buildImageThread, imageStore, allVMs):
        self._dnsmasq = dnsmasq
        self._broadcaster = broadcaster
        self._buildImageThread = buildImageThread
        self._imageStore = imageStore
        self._allVMs = allVMs
        self._allocations = []
        self._index = 1

    def create(self, requirements):
        assert globallock.assertLocked()
        self._cleanup()
        alloc = allocation.Allocation(
            index=self._index, requirements=requirements, dnsmasq=self._dnsmasq,
            broadcaster=self._broadcaster, buildImageThread=self._buildImageThread,
            imageStore=self._imageStore, allVMs=self._allVMs)
        self._allocations.append(alloc)
        self._index += 1
        return alloc

    def byIndex(self, index):
        assert globallock.assertLocked()
        self._cleanup()
        for alloc in self._allocations:
            if alloc.index() == index:
                return alloc
        raise IndexError("No such allocation")

    def all(self):
        assert globallock.assertLocked()
        self._cleanup()
        return self._allocations

    def _cleanup(self):
        self._allocations = [a for a in self._allocations if not a.deadForAWhile()]
