from rackattack.virtual.kvm import config
from rackattack.common import timer
from rackattack.virtual.kvm import vm
from rackattack.common import globallock
import time
import logging
import tempfile


class Allocation:
    _LIMBO_AFTER_DEATH_DURATION = 60
    _HEARTBEAT_TIMEOUT = 15

    def __init__(self, index, requirements, dnsmasq, broadcaster, buildImageThread, imageStore, allVMs):
        self._index = index
        self._requirements = requirements
        self._dnsmasq = dnsmasq
        self._broadcaster = broadcaster
        self._buildImageThread = buildImageThread
        self._imageStore = imageStore
        self._allVMs = allVMs
        self._vms = None
        self._death = None
        if len(self._requirements) > config.MAXIMUM_VMS:
            self._die(
                "Configured to disallow such a large allocation. Maximum is %d" % config.MAXIMUM_VMS)
            return
        self.heartbeat()
        logging.info("allocation created. requirements:\n%(requirements)s", dict(requirements=requirements))
        self._waitingForImages = 0
        self._enqueueBuildImages()
        if self._waitingForImages == 0:
            self._createVMs()

    def index(self):
        return self._index

    def vms(self):
        assert self.done()
        return self._vms

    def done(self):
        return self._vms is not None and len(self._vms) == len(self._requirements)

    def free(self):
        self._die("freed")

    def heartbeat(self):
        if self.dead():
            return
        timer.cancelAllByTag(tag=self)
        timer.scheduleIn(timeout=self._HEARTBEAT_TIMEOUT, callback=self._heartbeatTimeout, tag=self)

    def dead(self):
        assert self._death is None or self._vms is None
        if self._death is None:
            return None
        return self._death['reason']

    def deadForAWhile(self):
        if not self.dead():
            return False
        return self._death['when'] < time.time() - self._LIMBO_AFTER_DEATH_DURATION

    def createPostMortemPack(self):
        contents = []
        for name, vmInstance in self._vms.iteritems():
            contents.append("\n\n\n****************\n%s == %s\n******************" % (
                vmInstance.id(), name))
            with open(vmInstance.serialLogFilename(), "rb") as f:
                contents.append(f.read())
        filename = tempfile.mktemp()
        with open(filename, "wb") as f:
            f.write("\n".join(contents))
        return filename

    def _heartbeatTimeout(self):
        self._die("heartbeat timeout")

    def _die(self, reason):
        assert not self.dead()
        logging.info("Allocation dies of '%(reason)s'", dict(reason=reason))
        if self._vms is not None:
            for name, vmInstance in self._vms.iteritems():
                if vmInstance.index() in self._allVMs:
                    del self._allVMs[vmInstance.index()]
                vmInstance.destroy()
            self._vms = None
        self._death = dict(when=time.time(), reason=reason)
        timer.cancelAllByTag(tag=self)
        self._broadcaster.allocationChangedState(self._index)

    def _enqueueBuildImages(self):
        toEnqeue = set()
        for requirement in self._requirements.values():
            imageLabel = requirement['imageLabel']
            sizeGB = requirement['hardwareConstraints']['minimumDisk1SizeGB']
            try:
                self._imageStore.get(imageLabel, sizeGB)
            except:
                toEnqeue.add((imageLabel, sizeGB))
        for imageLabel, sizeGB in toEnqeue:
            self._broadcaster.allocationProviderMessage(
                self._index, "Label '%s' requires a qcow2 build. This takes several "
                "minutes per label and is requires once for each new label" % imageLabel)
            self._buildImageThread.enqueue(
                label=imageLabel, sizeGB=sizeGB, callback=self._buildImageThreadCallback)
            self._waitingForImages += 1

    def _buildImageThreadCallback(self, complete, message):
        assert globallock.assertLocked()
        if complete is None:
            self._broadcaster.allocationProviderMessage(self._index, message)
            return
        if complete:
            self._waitingForImages -= 1
            self._broadcaster.allocationProviderMessage(
                self._index, "QCOW2 built successfully. Waiting for %d more "
                "qcows to be built" % self._waitingForImages)
            if self._waitingForImages == 0:
                self._createVMs()
        else:
            self._die("unable to build image")

    def _createVMs(self):
        self._vms = dict()
        for name, requirement in self._requirements.iteritems():
            instance = vm.VM.createFromImageStore(
                index=self._availableIndex(), requirement=requirement, imageStore=self._imageStore)
            self._dnsmasq.addIfNotAlready(instance.primaryMACAddress(), instance.ipAddress())
            self._vms[name] = instance
            self._allVMs[instance.index()] = instance
        self._broadcaster.allocationChangedState(self._index)

    def _availableIndex(self):
        indices = set(xrange(1, len(self._allVMs) + 2))
        for index, vmInstance in self._allVMs.iteritems():
            assert vmInstance.index() == index
            indices.discard(vmInstance.index())
        return min(indices)
