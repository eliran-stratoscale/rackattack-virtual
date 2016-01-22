from rackattack.common import timer
import logging
from rackattack.common import globallock

STATE_SOFT_RECLAMATION = 1
STATE_COLD_RECLAMATION = 2
STATE_CHECKED_IN = 3
STATE_INAUGURATION_LABEL_PROVIDED = 4
STATE_INAUGURATION_DONE = 5
STATE_DESTROYED = 6


class HostStateMachine:
    TIMEOUT = {
        STATE_SOFT_RECLAMATION: 120,
        STATE_COLD_RECLAMATION: 10 * 60,
        STATE_INAUGURATION_LABEL_PROVIDED: 5 * 60}
    NR_CONSECUTIVE_ERRORS_BEFORE_DESTRUCTION = 5
    NR_CONSECUTIVE_ERRORS_BEFORE_RECONFIGURING_BIOS = 4
    NR_CONSECUTIVE_ERRORS_BEFORE_CLEARING_DISK = 2
    NR_CONSECUTIVE_ERRORS_BEFORE_HARD_RESET = 3
    ALLOW_CLEARING_OF_DISK = True

    def __init__(self, hostImplementation, inaugurate, tftpboot, dnsmasq, reclaimHost,
                 freshVMJustStarted=True, targetDevice=None):
        self._hostImplementation = hostImplementation
        self._targetDevice = hostImplementation.targetDevice()
        self._destroyCallback = None
        self._inaugurate = inaugurate
        self._tftpboot = tftpboot
        self._dnsmasq = dnsmasq
        self._slowReclaimCounter = 0
        self._stop = False
        self._stateChangeCallback = None
        self._imageLabel = None
        self._imageHint = None
        self._inaugurationProgressPercent = 0
        self._reclaimHost = reclaimHost
        self._inaugurate.register(
            id=hostImplementation.id(),
            checkInCallback=self._inauguratorCheckedIn,
            doneCallback=self._inauguratorDone,
            progressCallback=self._inauguratorProgress)
        self._configureForInaugurator()
        self._hasFirstReclamationOccurred = False
        if freshVMJustStarted:
            self._changeState(STATE_SOFT_RECLAMATION)
        else:
            self._coldReclaim()

    def setDestroyCallback(self, callback):
        self._destroyCallback = callback

    def hostImplementation(self):
        return self._hostImplementation

    def imageHint(self):
        return self._imageHint

    def imageLabel(self):
        return self._imageLabel

    def state(self):
        assert globallock.assertLocked()
        return self._state

    def unassign(self):
        assert globallock.assertLocked()
        assert self._stateChangeCallback is not None
        self._stateChangeCallback = None
        if self._state in [STATE_INAUGURATION_LABEL_PROVIDED, STATE_INAUGURATION_DONE]:
            self._softReclaim()

    def assign(self, stateChangeCallback, imageLabel, imageHint):
        assert globallock.assertLocked()
        assert self._stateChangeCallback is None
        assert stateChangeCallback is not None
        assert self._state not in [STATE_INAUGURATION_DONE, STATE_INAUGURATION_LABEL_PROVIDED]
        self._stateChangeCallback = stateChangeCallback
        self._imageLabel = imageLabel
        self._imageHint = imageHint
        if self._state == STATE_CHECKED_IN:
            self._provideLabel()

    def destroy(self):
        assert globallock.assertLocked()
        logging.info("destroying host %(host)s", dict(host=self._hostImplementation.id()))
        self._inaugurate.unregister(self._hostImplementation.id())
        self._changeState(STATE_DESTROYED)
        self._hostImplementation.destroy()
        self._destroyCallback(self)
        assert self._destroyCallback is not None
        self._destroyCallback = None

    def _inauguratorCheckedIn(self):
        assert globallock.assertLocked()
#        assert self._state in [
#            STATE_COLD_RECLAMATION, STATE_SOFT_RECLAMATION]
        if self._state not in [STATE_COLD_RECLAMATION, STATE_SOFT_RECLAMATION]:
            logging.error("expected reclamation state, found %(state)s", dict(state=self._state))
#####

        if self._stateChangeCallback is not None:
            self._provideLabel()
        else:
            self._changeState(STATE_CHECKED_IN)

    def _inauguratorDone(self):
        assert globallock.assertLocked()
        if self._state != STATE_INAUGURATION_LABEL_PROVIDED:
            logging.error('Got an inauguration-done message for %(server)s in state %(state)s, ignoring.',
                          dict(server=self._hostImplementation.id(), state=self._state))
            return
        self._slowReclaimCounter = 0
        if self._stateChangeCallback is not None:
            self._tftpboot.configureForLocalBoot(self._hostImplementation.primaryMACAddress())
            self._changeState(STATE_INAUGURATION_DONE)

    def _timeout(self):
        assert globallock.assertLocked()
        logging.warning("Timeout for host %(id)s at state %(state)s", dict(
            id=self._hostImplementation.id(), state=self._state))
        if self._state in (STATE_COLD_RECLAMATION, STATE_SOFT_RECLAMATION):
            self._coldReclaim()
        else:
            self._softReclaim()

    def softReclaimFailed(self):
        assert globallock.assertLocked()
        assert self._state in [STATE_SOFT_RECLAMATION, STATE_DESTROYED]
        if self._state != STATE_SOFT_RECLAMATION:
            logging.warning("Ignoring soft reclamation failure, node already destroyed")
            return
        logging.warning("Soft reclaimation for host %(id)s failed, reverting to cold reclaimation. Previous"
                        " label=%(previousLabel)s",
                        dict(id=self._hostImplementation.id(), previousLabel=self._imageLabel))
        self._coldReclaim()

    def _provideLabel(self):
        logging.info("Node %(id)s being provided a label '%(label)s'", dict(
            id=self._hostImplementation.id(), label=self._imageLabel))
        self._inaugurate.provideLabel(
            id=self._hostImplementation.id(), label=self._imageLabel)
        self._inaugurationProgressPercent = 0
        self._changeState(STATE_INAUGURATION_LABEL_PROVIDED)

    def _clearDiskOnSlowReclaim(self):
        if self.ALLOW_CLEARING_OF_DISK:
            return self._slowReclaimCounter > self.NR_CONSECUTIVE_ERRORS_BEFORE_CLEARING_DISK
        return False

    def _initializeBIOSOnSlowReclaim(self):
        return self._slowReclaimCounter > self.NR_CONSECUTIVE_ERRORS_BEFORE_RECONFIGURING_BIOS

    def _hardResetOnColdReclaim(self):
        if not self._hasFirstReclamationOccurred:
            self._hasFirstReclamationOccurred = True
            return True
        return self._slowReclaimCounter > self.NR_CONSECUTIVE_ERRORS_BEFORE_HARD_RESET

    def _coldReclaim(self):
        assert self._destroyCallback is not None or self._slowReclaimCounter == 0
        self._slowReclaimCounter += 1
        if self._slowReclaimCounter > self.NR_CONSECUTIVE_ERRORS_BEFORE_DESTRUCTION:
            logging.error("Cold reclaims retries exceeded, destroying host %(id)s", dict(
                id=self._hostImplementation.id()))
            assert self._destroyCallback is not None
            self.destroy()
            assert self._destroyCallback is None
            return
        logging.info("Node is being cold reclaimed %(id)s", dict(
            id=self._hostImplementation.id()))
        self._configureForInaugurator(clearDisk=self._clearDiskOnSlowReclaim())
        self._changeState(STATE_COLD_RECLAMATION)
        self._reclaimHost.cold(self._hostImplementation,
                               reconfigureBIOS=self._initializeBIOSOnSlowReclaim(),
                               hardReset=self._hardResetOnColdReclaim())

    def _softReclaim(self):
        assert self._destroyCallback is not None
        logging.info("Node is being soft reclaimed %(id)s", dict(id=self._hostImplementation.id()))
        isInauguratorActive = self._state in (STATE_CHECKED_IN, STATE_INAUGURATION_LABEL_PROVIDED)
        self._changeState(STATE_SOFT_RECLAMATION)
        self._configureForInaugurator()
        self._reclaimHost.soft(self._hostImplementation, isInauguratorActive)

    def _changeState(self, state):
        timer.cancelAllByTag(tag=self)
        self._state = state
        if state in self.TIMEOUT:
            timer.scheduleIn(timeout=self.TIMEOUT[state], callback=self._timeout, tag=self)
        if self._stateChangeCallback is not None:
            self._stateChangeCallback(self)

    def _configureForInaugurator(self, clearDisk=False):
        self._dnsmasq.addIfNotAlready(
            self._hostImplementation.primaryMACAddress(), self._hostImplementation.ipAddress())
        self._tftpboot.configureForInaugurator(
            self._hostImplementation.id(),
            self._hostImplementation.primaryMACAddress(),
            self._hostImplementation.ipAddress(),
            clearDisk=clearDisk,
            targetDevice=self._targetDevice)

    def _inauguratorProgress(self, progress):
        if self._state not in [STATE_INAUGURATION_LABEL_PROVIDED, STATE_CHECKED_IN]:
            logging.error("Progress message in invalid state: %(state)s", dict(state=self._state))
            return
        if self._state == STATE_CHECKED_IN:
            return
        if 'state' not in progress or 'percent' not in progress:
            logging.error("Invalid progress message: %(progress)s", dict(progress=progress))
            return
        if progress['state'] != 'fetching':
            return
        if progress[u'percent'] != self._inaugurationProgressPercent:
            self._inaugurationProgressPercent = progress[u'percent']
            timer.cancelAllByTag(tag=self)
            timer.scheduleIn(timeout=self.TIMEOUT[STATE_INAUGURATION_LABEL_PROVIDED],
                             callback=self._timeout, tag=self)
