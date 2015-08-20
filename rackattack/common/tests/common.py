import mock
from rackattack.common import hoststatemachine


class FakeHost:
    def id(self):
        return "fake id"

    def primaryMACAddress(self):
        return "fake primary mac"

    def ipAddress(self):
        return "fake ip address"

    def sshCredentials(self):
        return dict(fakeSSHCredentials=True)

    def destroy(self):
        assert self.expectedDestroy
        self.expectedDestroy = False

    def reconfigureBIOS(self):
        pass

    def rootSSHCredentials(self):
        return dict(hostname="alpha", username="bravo", password="charlie")

    def primaryMacAddress(self):
        return "delta-echo-foxtrot"


class FakeTFTPBoot:
    def inauguratorCommandLine(self, *args):
        return "Wow this totally looks like an inaugurator command line %(args)s" % \
            dict(args=str(args))


class FakeHostStateMachine:
    def __init__(self, hostImplementation, *args, **kwargs):
        self._hostImplementation = hostImplementation
        self._destroyCallback = None
        self._state = hoststatemachine.STATE_CHECKED_IN
        self._stateChangeCallback = None
        self._imageLabel = None
        self._imageHint = None
        self.softReclaimFailed = mock.Mock()

    def hostImplementation(self):
        return self._hostImplementation

    def setDestroyCallback(self, callback):
        self._destroyCallback = callback

    def destroy(self, forgetCallback=False):
        self._state = hoststatemachine.STATE_DESTROYED
        if not forgetCallback:
            self._destroyCallback(self)

    def isDestroyed(self):
        return self._state == hoststatemachine.STATE_DESTROYED

    def state(self):
        return self._state

    def assign(self, stateChangeCallback, imageLabel, imageHint):
        self._stateChangeCallback = stateChangeCallback
        self._imageLabel = imageLabel
        self._imageHint = imageHint

    def unassign(self):
        self._stateChangeCallback = None

    def isAssigned(self):
        return self._stateChangeCallback is not None

    def fakeInaugurationDone(self):
        self._state = hoststatemachine.STATE_INAUGURATION_DONE
        self._stateChangeCallback(self)
