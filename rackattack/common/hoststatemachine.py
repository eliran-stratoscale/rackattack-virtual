from rackattack.common import timer
import logging
from rackattack.common import reclaimhost
from rackattack.common import globallock

STATE_QUICK_RECLAIMATION_IN_PROGRESS = 1
STATE_SLOW_RECLAIMATION_IN_PROGRESS = 2
STATE_CHECKED_IN = 3
STATE_INAUGURATION_LABEL_PROVIDED = 4
STATE_INAUGURATION_DONE = 5
STATE_DESTROYED = 6


class HostStateMachine:
    _TIMEOUT = {
        STATE_QUICK_RECLAIMATION_IN_PROGRESS: 120,
        STATE_SLOW_RECLAIMATION_IN_PROGRESS: 7 * 60,
        STATE_INAUGURATION_LABEL_PROVIDED: 7 * 60}
    _COLD_RECLAIMS_RETRIES = 5
    _COLD_RECLAIM_RECONFIGURE_BIOS = 4
    _COLD_RECLAIMS_RETRIES_BEFORE_CLEARING_DISK = 2

    def __init__(self, hostImplementation, inaugurate, tftpboot, freshVMJustStarted=True):
        self._hostImplementation = hostImplementation
        self._destroyCallback = None
        self._inaugurate = inaugurate
        self._tftpboot = tftpboot
        self._slowReclaimCounter = 0
        self._stop = False
        self._stateChangeCallback = None
        self._imageLabel = None
        self._imageHint = None
        self._inaugurate.register(
            ipAddress=hostImplementation.ipAddress(),
            checkInCallback=self._inauguratorCheckedIn,
            doneCallback=self._inauguratorDone)
        self._tftpboot.configureForInaugurator(
            self._hostImplementation.primaryMACAddress(), self._hostImplementation.ipAddress())
        if freshVMJustStarted:
            self._changeState(STATE_QUICK_RECLAIMATION_IN_PROGRESS)
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
        self._inaugurate.unregister(self._hostImplementation.ipAddress())
        self._changeState(STATE_DESTROYED)
        assert self._destroyCallback is not None
        self._destroyCallback = None
        self._hostImplementation.destroy()

    def _inauguratorCheckedIn(self):
        assert globallock.assertLocked()
#        assert self._state in [
#            STATE_SLOW_RECLAIMATION_IN_PROGRESS, STATE_QUICK_RECLAIMATION_IN_PROGRESS]
        if self._state not in [STATE_SLOW_RECLAIMATION_IN_PROGRESS, STATE_QUICK_RECLAIMATION_IN_PROGRESS]:
            logging.error("expected reclamation state, found %(state)s", dict(state=self._state))
#####

        if self._stateChangeCallback is not None:
            self._provideLabel()
        else:
            self._changeState(STATE_CHECKED_IN)

    def _inauguratorDone(self):
        assert globallock.assertLocked()
        assert self._state == STATE_INAUGURATION_LABEL_PROVIDED
        self._slowReclaimCounter = 0
        if self._stateChangeCallback is not None:
            self._tftpboot.configureForLocalBoot(self._hostImplementation.primaryMACAddress())
            self._changeState(STATE_INAUGURATION_DONE)

    def _timeout(self):
        assert globallock.assertLocked()
        logging.warning("Timeout for host %(id)s at state %(state)s", dict(
            id=self._hostImplementation.id(), state=self._state))
        self._coldReclaim()

    def _softReclaimFailed(self):
        assert globallock.assertLocked()
        assert self._state in [STATE_QUICK_RECLAIMATION_IN_PROGRESS, STATE_DESTROYED]
        if self._state != STATE_QUICK_RECLAIMATION_IN_PROGRESS:
            logging.warning("Ignoring soft reclamation failure, node already destroyed")
            return
        logging.warning(
            "Soft reclaimation for host %(id)s failed, reverting to cold reclaimation",
            dict(id=self._hostImplementation.id(), state=self._state))
        self._coldReclaim()

    def _provideLabel(self):
        try:
            logging.info("Node %(id)s being provided a label '%(label)s'", dict(
                id=self._hostImplementation.id(), label=self._imageLabel))
            self._inaugurate.provideLabel(
                ipAddress=self._hostImplementation.ipAddress(), label=self._imageLabel)
            self._changeState(STATE_INAUGURATION_LABEL_PROVIDED)
        except:
            logging.exception("Unable to provide label, cold reclaiming host %(host)s", dict(
                host=self._hostImplementation.id()))
            self._coldReclaim()

    def _clearDiskOnSlowReclaim(self):
        return self._slowReclaimCounter > self._COLD_RECLAIMS_RETRIES_BEFORE_CLEARING_DISK

    def _initializeBIOSOnSlowReclaim(self):
        return self._slowReclaimCounter > self._COLD_RECLAIM_RECONFIGURE_BIOS

    def _coldReclaim(self):
        assert self._destroyCallback is not None or self._slowReclaimCounter == 0
        self._slowReclaimCounter += 1
        if self._slowReclaimCounter > self._COLD_RECLAIMS_RETRIES:
            logging.error("Cold reclaims retries exceeded, destroying host %(id)s", dict(
                id=self._hostImplementation.id()))
            assert self._destroyCallback is not None
            self._destroyCallback(self)  # expected: caller will call self.destroy
            assert self._destroyCallback is None
            return
        logging.info("Node is being cold reclaimed %(id)s", dict(
            id=self._hostImplementation.id()))
        self._tftpboot.configureForInaugurator(
            self._hostImplementation.primaryMACAddress(), self._hostImplementation.ipAddress(),
            clearDisk=self._clearDiskOnSlowReclaim())
        self._changeState(STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        reclaimhost.ReclaimHost.cold(self._hostImplementation, self._tftpboot,
                                     reconfigureBIOS=self._initializeBIOSOnSlowReclaim())

    def _softReclaim(self):
        assert self._destroyCallback is not None
        logging.info("Node is being soft reclaimed %(id)s", dict(id=self._hostImplementation.id()))
        self._changeState(STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self._tftpboot.configureForInaugurator(
            self._hostImplementation.primaryMACAddress(), self._hostImplementation.ipAddress())
        reclaimhost.ReclaimHost.soft(self._hostImplementation, self._tftpboot, self._softReclaimFailed)

    def _changeState(self, state):
        timer.cancelAllByTag(tag=self)
        self._state = state
        if state in self._TIMEOUT:
            timer.scheduleIn(timeout=self._TIMEOUT[state], callback=self._timeout, tag=self)
        if self._stateChangeCallback is not None:
            self._stateChangeCallback(self)
