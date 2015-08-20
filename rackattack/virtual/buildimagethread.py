import threading
import logging
from rackattack.virtual import sh
from rackattack.common import globallock
import Queue
from rackattack.tcp import suicide
from rackattack import api
from rackattack.virtual.kvm import config
from rackattack.virtual.kvm import vm
from rackattack.common import hoststatemachine


class BuildImageThread(threading.Thread):
    def __init__(self, inaugurate, tftpboot, dnsmasq, imageStore, reclaimHost):
        self._inaugurate = inaugurate
        self._tftpboot = tftpboot
        self._dnsmasq = dnsmasq
        self._imageStore = imageStore
        self._reclaimhost = reclaimHost
        self._busy = True
        self._queue = Queue.Queue()
        self._event = threading.Event()
        threading.Thread.__init__(self)
        self.daemon = True
        self._reclaimHost = reclaimHost
        threading.Thread.start(self)

    def enqueue(self, label, sizeGB, callback):
        assert globallock.assertLocked()
        if self._busy:
            callback(None, "Image builder still busy with previous tasks, waiting in queue")
        self._queue.put((label, sizeGB, callback))

    def run(self):
        try:
            while True:
                self._work()
        except:
            logging.exception("Build Image Thread terminates, commiting suicide")
            suicide.killSelf()

    def _work(self):
        self._busy = False
        label, sizeGB, callback = self._queue.get()
        self._busy = True
        with globallock.lock():
            callback(None, "Localizing label %s" % label)
        logging.info("Localizing label '%(label)s'", dict(label=label))
        try:
            sh.run(["solvent", "localize", "--label", label])
        except Exception as e:
            logging.exception("Unable to localize label '%(label)s'", dict(label=label))
            with globallock.lock():
                callback(False, "Unable to localize label '%s': '%s'" % (label, str(e)))
            return
        with globallock.lock():
            callback(None, "Done localizing label %s, Building image using inaugurator" % label)
        logging.info("Done localizing label '%(label)s', building image using inaugurator", dict(
            label=label))
        vmInstance, stateMachine = self._startInauguratorVM(label, sizeGB)
        self._event.wait()
        self._event.clear()
        with globallock.lock():
            assert stateMachine.state() in [
                hoststatemachine.STATE_INAUGURATION_DONE, hoststatemachine.STATE_DESTROYED]
            if stateMachine.state() == hoststatemachine.STATE_DESTROYED:
                logging.error("Unable to build image using inaugurator")
                callback(False, "Unable to build image using inaugurator. Review rackattack provider logs")
                return
            self._imageStore.put(filename=vmInstance.disk1Image(), imageLabel=label, sizeGB=sizeGB)
            stateMachine.unassign()
            stateMachine.destroy()
            callback(True, "Done building image using inaugurator (label %s)" % label)
        logging.info("Done building image using inaugurator (label %(label)s)", dict(label=label))

    def _vmCommitedSuicide(self, stateMachine):
        pass

    def _vmChangedState(self, stateMachine):
        if stateMachine.state() in [
                hoststatemachine.STATE_INAUGURATION_DONE, hoststatemachine.STATE_DESTROYED]:
            self._event.set()

    def _startInauguratorVM(self, label, sizeGB):
        with globallock.lock():
            requirement = api.Requirement(
                imageLabel=label, imageHint="build", hardwareConstraints=dict(
                    minimumDisk1SizeGB=sizeGB, minimumDisk2SizeGB=1)).__dict__
            vmInstance = vm.VM.createFromNewImage(config.IMAGE_BUILDING_VM_INDEX, requirement)
            stateMachine = hoststatemachine.HostStateMachine(
                vmInstance, self._inaugurate, self._tftpboot, self._dnsmasq, self._reclaimHost)
            stateMachine.assign(self._vmChangedState, imageLabel=label, imageHint="build")
            stateMachine.setDestroyCallback(self._vmCommitedSuicide)
            return vmInstance, stateMachine
