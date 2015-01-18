import unittest
from rackattack.common import hoststatemachine
from rackattack.common import reclaimhost
from rackattack.common import globallock
from rackattack.common import timer


class Empty:
    pass


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


class Test(unittest.TestCase):
    def setUp(self):
        globallock._lock.acquire()
        self.checkInCallback = None
        self.doneCallback = None
        self.expectedProvidedLabel = None
        self.provideLabelRaises = False
        self.expectedReportedState = None
        timer.scheduleIn = self.scheduleTimerIn
        timer.cancelAllByTag = self.cancelAllTimersByTag
        self.currentTimer = None
        self.currentTimerTag = None
        self.expectedTFTPBootToBeConfiguredForInaugurator = False
        self.expectedTFTPBootToBeConfiguredForLocalHost = False
        self.expectedColdReclaim = False
        self.expectReconfigureBIOS = False
        self.expectedSoftReclaim = False
        self.expectedSelfDestruct = False
        self.softReclaimFailedCallback = None
        self.construct()

    def tearDown(self):
        globallock._lock.release()

    def construct(self):
        self.hostImplementation = FakeHost()
        self.fakeInaugurate = Empty()
        self.fakeInaugurate.provideLabel = self.provideLabelForInauguration
        self.fakeInaugurate.register = self.registerForInauguration
        self.fakeInaugurate.unregister = self.unregisterForInauguration
        self.fakeTFTPBoot = Empty()
        self.fakeTFTPBoot.inauguratorCommandLine = self.inauguratorCommandLine
        self.fakeTFTPBoot.configureForInaugurator = self.tftpbootConfigureForInaugurator
        self.fakeTFTPBoot.configureForLocalBoot = self.tftpbootConfigureForLocalBoot
        reclaimhost.ReclaimHost = Empty()
        reclaimhost.ReclaimHost.cold = self.reclaimHostCold
        reclaimhost.ReclaimHost.soft = self.reclaimHostSoft
        self.expectedTFTPBootToBeConfiguredForInaugurator = True
        self.expectedClearDisk = False
        self.tested = hoststatemachine.HostStateMachine(
            hostImplementation=self.hostImplementation,
            inaugurate=self.fakeInaugurate, tftpboot=self.fakeTFTPBoot)
        self.tested.setDestroyCallback(self.destroyHost)
        self.assertIs(self.tested.hostImplementation(), self.hostImplementation)
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForInaugurator)
        assert self.checkInCallback is not None
        assert self.doneCallback is not None

    def destroyHost(self, stateMachine):
        self.assertIs(stateMachine, self.tested)
        self.assertTrue(self.expectedSelfDestruct)
        self.expectedSelfDestruct = False
        self.tested.destroy()

    def scheduleTimerIn(self, timeout, callback, tag):
        self.assertIs(self.currentTimer, None)
        self.assertIs(self.currentTimerTag, None)
        self.currentTimer = callback
        self.currentTimerTag = tag

    def cancelAllTimersByTag(self, tag):
        if self.currentTimerTag is not None:
            self.assertIsNot(self.currentTimer, None)
            self.assertIs(self.currentTimerTag, tag)
        self.currentTimer = None
        self.currentTimerTag = None

    def triggerTimeout(self):
        self.assertIsNot(self.currentTimer, None)
        self.assertIsNot(self.currentTimerTag, None)
        self.currentTimer()
        self.currentTimer = None
        self.currentTimerTag = None

    def inauguratorCommandLine(self, mac, ip):
        self.assertEquals(mac, self.hostImplementation.primaryMACAddress())
        self.assertEquals(ip, self.hostImplementation.ipAddress())
        return "fake inaugurator command line"

    def registerForInauguration(self, ipAddress, checkInCallback, doneCallback):
        self.assertEquals(ipAddress, self.hostImplementation.ipAddress())
        self.assertIs(self.checkInCallback, None)
        self.assertIs(self.doneCallback, None)
        self.checkInCallback = checkInCallback
        self.doneCallback = doneCallback

    def unregisterForInauguration(self, ipAddress):
        self.assertIsNot(self.checkInCallback, None)
        self.assertIsNot(self.doneCallback, None)
        self.checkInCallback = None
        self.doneCallback = None

    def provideLabelForInauguration(self, ipAddress, label):
        self.assertEquals(ipAddress, self.hostImplementation.ipAddress())
        if self.provideLabelRaises:
            raise Exception("Provide label raises on purpose, as part of test")
        self.assertEquals(label, self.expectedProvidedLabel)
        self.expectedProvidedLabel = None

    def isObjectInitialized(self):
        return hasattr(self, 'tested')

    def tftpbootConfigureForInaugurator(self, mac, ip, clearDisk=False):
        self.assertEquals(mac, self.hostImplementation.primaryMACAddress())
        self.assertEquals(ip, self.hostImplementation.ipAddress())
        self.assertTrue(self.expectedTFTPBootToBeConfiguredForInaugurator)
        self.assertEquals(clearDisk, self.expectedClearDisk)
        self.expectedTFTPBootToBeConfiguredForInaugurator = False

    def tftpbootConfigureForLocalBoot(self, mac):
        self.assertEquals(mac, self.hostImplementation.primaryMACAddress())
        self.assertTrue(self.expectedTFTPBootToBeConfiguredForLocalHost)
        self.expectedTFTPBootToBeConfiguredForLocalHost = False

    def reclaimHostCold(self, hostImplementation, tftpboot, reconfigureBIOS=False):
        self.assertIs(hostImplementation, self.hostImplementation)
        self.assertIs(tftpboot, self.fakeTFTPBoot)
        self.assertTrue(self.expectedColdReclaim)
        self.expectedColdReclaim = False
        self.assertEqual(self.expectReconfigureBIOS, reconfigureBIOS)

    def reclaimHostSoft(self, hostImplementation, tftpboot, failedCallback):
        self.assertIs(hostImplementation, self.hostImplementation)
        self.assertIs(tftpboot, self.fakeTFTPBoot)
        self.assertTrue(self.expectedSoftReclaim)
        self.expectedSoftReclaim = False
        self.softReclaimFailedCallback = failedCallback

    def checkInCallbackProvidedLabelImmidiately(self, label):
        self.assertIn(self.tested.state(), [
            hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS,
            hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS])
        self.assertIs(self.expectedProvidedLabel, None)
        self.expectedProvidedLabel = label
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.checkInCallback()
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)

    def stateChangedCallback(self, tested):
        self.assertIs(tested, self.tested)
        self.assertIsNot(self.expectedReportedState, None)
        self.assertEquals(tested.state(), self.expectedReportedState)
        self.expectedReportedState = None

    def inaugurationDone(self):
        self.assertIn(self.tested.state(), [hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED])
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_DONE
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForLocalHost)
        self.expectedTFTPBootToBeConfiguredForLocalHost = True
        self.doneCallback()
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForLocalHost)
        self.assertIs(self.currentTimer, None)

    def assign(self, label, hint):
        self.tested.assign(self.stateChangedCallback, label, hint)
        self.assertEquals(self.tested.imageLabel(), label)
        self.assertEquals(self.tested.imageHint(), hint)

    def test_vmLifeCycle_Normal(self):
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.assign("fake image label", "fake image hint")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)

    def unassignCausesSoftReclaim(self):
        self.assertFalse(self.expectedSoftReclaim)
        self.expectedSoftReclaim = True
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForInaugurator)
        self.expectedTFTPBootToBeConfiguredForInaugurator = True
        self.tested.unassign()
        self.assertFalse(self.expectedSoftReclaim)
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForInaugurator)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)

    def callCausesColdReclaim(self, call):
        self.assertFalse(self.expectedColdReclaim)
        self.expectedColdReclaim = True
        self.expectedTFTPBootToBeConfiguredForInaugurator = True
        call()
        self.assertFalse(self.expectedColdReclaim)
        self.assertFalse(self.expectedTFTPBootToBeConfiguredForInaugurator)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)

    def callCausesColdReclaimAndStateChange(self, call, state):
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = state
        self.callCausesColdReclaim(call)
        self.assertIs(self.expectedReportedState, None)

    def test_vmLifeCycle_OrderlyRelease(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)

    def test_vmLifeCycle_OrderlyRelease_QuickReclaimationDidNotWork(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.callCausesColdReclaim(self.softReclaimFailedCallback)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)

    def assignCallbackProvidedLabelImmidiately(self, label, hint):
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.assertIs(self.expectedProvidedLabel, None)
        self.expectedProvidedLabel = label
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.assign(label, hint)
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)

    def test_vmLifeCycle_Reuse_ReachedCheckeInBeforeReuse(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.checkInCallbackLingers()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.assignCallbackProvidedLabelImmidiately("fake image label 2", "fake image hint 2")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()

    def test_vmLifeCycle_Reuse_ReassignedBeforeReachingCheckeIn(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.assign("fake image label 2", "fake image hint 2")
        self.checkInCallbackProvidedLabelImmidiately("fake image label 2")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()

    def checkInCallbackLingers(self):
        self.assertIn(self.tested.state(), [
            hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS,
            hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS])
        self.checkInCallback()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.assertIs(self.currentTimer, None)

    def test_vmLifeCycle_QuickReclaimationFailedWhenAssigned_UserDecidesToUnassign(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.assign("fake image label", "fake image hint")
        self.assertIsNot(self.softReclaimFailedCallback, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_QUICK_RECLAIMATION_IN_PROGRESS)
        self.callCausesColdReclaimAndStateChange(
            self.softReclaimFailedCallback, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.tested.unassign()
        self.checkInCallbackLingers()

    def test_vmLifeCycle_QuickReclaimationFailedWithTimeoutWhenAssigned_UserDecidesToUnassign(self):
        self.assign("fake image label", "fake image hint")
        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.tested.unassign()
        self.checkInCallbackLingers()

    def test_coldReclaimationSavesTheDay(self):
        self.callCausesColdReclaim(self.currentTimer)
        self.checkInCallbackLingers()

    def timerCausesSelfDestruct(self):
        self.assertFalse(self.expectedSelfDestruct)
        self.expectedSelfDestruct = True
        self.hostImplementation.expectedDestroy = True
        self.currentTimer()
        self.assertFalse(self.expectedSelfDestruct)
        self.assertFalse(self.hostImplementation.expectedDestroy)

    def timerCausesSelfDestructAndStateChange(self):
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_DESTROYED
        self.timerCausesSelfDestruct()
        self.assertIs(self.expectedReportedState, None)

    def test_vmLifeCycle_AllReclaimationRetriesFail_NoUser(self):
        self.callCausesColdReclaim(self.currentTimer)
        self.callCausesColdReclaim(self.currentTimer)
        self.expectedClearDisk = True
        self.callCausesColdReclaim(self.currentTimer)
        self.callCausesColdReclaim(self.currentTimer)
        self.expectReconfigureBIOS = True
        self.callCausesColdReclaim(self.currentTimer)
        self.timerCausesSelfDestruct()

    def test_vmLifeCycle_AllReclaimationRetriesFail_WithUser(self):
        self.assign("fake image label", "fake image hint")
        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)

        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.expectedClearDisk = True
        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.expectReconfigureBIOS = True
        self.callCausesColdReclaimAndStateChange(
            self.currentTimer, hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)
        self.timerCausesSelfDestructAndStateChange()

    def test_vmLifeCycle_UnableToProvideLabel_ColdReclaim(self):
        self.assign("fake image label", "fake image hint")
        self.checkInCallbackProvidedLabelImmidiately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.checkInCallbackLingers()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.provideLabelRaises = True
        self.expectedReportedState = hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS
        self.expectedTFTPBootToBeConfiguredForInaugurator = True
        self.expectedColdReclaim = True
        self.assign("fake image label", "fake image hint")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SLOW_RECLAIMATION_IN_PROGRESS)


if __name__ == '__main__':
    unittest.main()
