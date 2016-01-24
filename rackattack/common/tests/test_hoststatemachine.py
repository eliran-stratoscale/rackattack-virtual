import os
import mock
import logging
import unittest
from rackattack.common import hoststatemachine
from rackattack.common import globallock
from rackattack.common import timer
from rackattack.common.tests.common import FakeHost
from rackattack.common import reclaimhostspooler


class Empty:
    pass


class FakeTFTPBoot:
    def __init__(self, test):
        self.inauguratorCommandLine = mock.Mock(side_effect=self._inauguratorCommandLine)
        self.configureForInaugurator = mock.Mock(side_effect=self._configureForInaugurator)
        self.configureForLocalBoot = mock.Mock(side_effect=self._configureForLocalBoot)
        self.test = test
        self.expectedToBeConfiguredForLocalBoot = False
        self.expectedToBeConfiguredForInaugurator = False
        self._reset()

    def expectToBeConfiguredForInaugurator(self):
        self.test.assertFalse(self.expectedToBeConfiguredForInaugurator)
        self.expectedToBeConfiguredForInaugurator = True

    def expectToBeConfiguredForLocalBoot(self):
        self.test.assertFalse(self.expectedToBeConfiguredForLocalBoot)
        self.expectedToBeConfiguredForLocalBoot = True

    def validateConfiguredOnceForInaugurator(self):
        callCount = self.configureForInaugurator.call_count
        self.configureForInaugurator.reset_mock()
        self.test.assertEquals(callCount, 1)

    def validateConfiguredOnceForLocalBoot(self):
        callCount = self.configureForLocalBoot.call_count
        self.configureForLocalBoot.reset_mock()
        self.test.assertEquals(callCount, 1)

    def _inauguratorCommandLine(self, id, mac, ip):
        self.test.assertEquals(id, self.test.hostImplementation.id())
        self.test.assertEquals(mac, self.test.hostImplementation.primaryMACAddress())
        self.test.assertEquals(ip, self.test.hostImplementation.ipAddress())
        return "fake inaugurator command line"

    def _reset(self):
        self.expectedToBeConfiguredForLocalBoot = False
        self.expectedToBeConfiguredForInaugurator = False
        self.inauguratorCommandLine.reset_mock()
        self.configureForInaugurator.reset_mock()
        self.configureForLocalBoot.reset_mock()

    def _configureForInaugurator(self, id, mac, ip, clearDisk=False, targetDevice=None):
        self.test.assertEquals(id, self.test.hostImplementation.id())
        self.test.assertEquals(mac, self.test.hostImplementation.primaryMACAddress())
        self.test.assertEquals(ip, self.test.hostImplementation.ipAddress())
        self.test.assertTrue(self.expectedToBeConfiguredForInaugurator)
        self.test.assertEquals(clearDisk, self.test.expectedClearDisk)
        self.expectedToBeConfiguredForInaugurator = False

    def _configureForLocalBoot(self, mac):
        self.test.assertEquals(mac, self.test.hostImplementation.primaryMACAddress())
        self.test.assertTrue(self.expectedToBeConfiguredForLocalBoot)
        self.expectedToBeConfiguredForLocalBoot = False


class Test(unittest.TestCase):
    def setUp(self):
        globallock._lock.acquire()
        self.addCleanup(self.releaseGlobalLock)
        self.checkInCallback = None
        self.doneCallback = None
        self.failureCallback = None
        self.expectedProvidedLabel = None
        self.provideLabelRaises = False
        self.expectedReportedState = None
        timer.scheduleIn = self.scheduleTimerIn
        timer.cancelAllByTag = self.cancelAllTimersByTag
        self.currentTimer = None
        self.currentTimerTag = None
        self.expectedColdReclaim = False
        self.expectReconfigureBIOS = False
        self.expectedHardReset = True
        self.expectedSoftReclaim = False
        self.expectedSelfDestruct = False
        self.softReclaimFailedCallback = None
        self.construct()

    @classmethod
    def setUpClass(cls):
        cls.configureLogging()

    @classmethod
    def configureLogging(self):
        logger = logging.getLogger()
        verbosity = int(os.getenv("VERBOSITY", 0))
        logLevels = {0: logging.CRITICAL + 1,
                     1: logging.ERROR,
                     2: logging.INFO,
                     3: logging.DEBUG}
        maxVerbosity = max(logLevels.keys())
        if verbosity > maxVerbosity:
            verbosity = maxVerbosity
        elif verbosity < 0:
            verbosity = 0
        logLevel = logLevels[verbosity]
        logger.setLevel(logLevel)

    def releaseGlobalLock(self):
        globallock._lock.release()

    def construct(self):
        self.hostImplementation = FakeHost()
        self.fakeInaugurate = Empty()
        self.fakeInaugurate.provideLabel = self.provideLabelForInauguration
        self.fakeInaugurate.register = self.registerForInauguration
        self.fakeInaugurate.unregister = self.unregisterForInauguration
        self.fakeTFTPBoot = FakeTFTPBoot(self)
        self.fakeDnsmasq = Empty()
        self.fakeDnsmasq.addIfNotAlready = self.dnsmasqAddIfNotAlready
        self.fakeReclaimHost = Empty()
        self.patchWithSpecValidation(fakeObject=self.fakeReclaimHost,
                                     realMethod=reclaimhostspooler.ReclaimHostSpooler.cold,
                                     fakeMethod=self.reclaimHostCold)
        self.patchWithSpecValidation(fakeObject=self.fakeReclaimHost,
                                     realMethod=reclaimhostspooler.ReclaimHostSpooler.soft,
                                     fakeMethod=self.reclaimHostSoft)
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.expectedDnsmasqAddIfNotAlready = True
        self.expectedClearDisk = False
        hoststatemachine.HostStateMachine.ALLOW_CLEARING_OF_DISK = True
        self.tested = hoststatemachine.HostStateMachine(
            hostImplementation=self.hostImplementation,
            inaugurate=self.fakeInaugurate, tftpboot=self.fakeTFTPBoot, dnsmasq=self.fakeDnsmasq,
            reclaimHost=self.fakeReclaimHost)
        self.tested.setDestroyCallback(self.destroyHost)
        self.assertIs(self.tested.hostImplementation(), self.hostImplementation)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()
        assert self.checkInCallback is not None
        assert self.doneCallback is not None

    def patchWithSpecValidation(self, fakeObject, realMethod, fakeMethod):
        specValidator = mock.create_autospec(realMethod)
        methodName = realMethod.__name__

        def useFakeMethodWithSpecValidation(*args, **kwargs):
            fakeSelf = None
            try:
                specValidator(fakeSelf, *args, **kwargs)
            except TypeError as ex:
                msg = "It seems that method '%(methodName)s' was used with the wrong argument " \
                      "specification; args:%(args)s, kwargs: %(kwargs)s " \
                      % dict(methodName=methodName, args=args, kwargs=kwargs)
                ex.message = "%(msg)s. Original message: '%(origMessage)s'." % dict(msg=msg,
                                                                                    origMessage=ex.message)
                ex.args = (ex.message,)
                raise ex
            fakeMethod(*args, **kwargs)
        setattr(fakeObject, methodName, useFakeMethodWithSpecValidation)

    def destroyHost(self, stateMachine):
        self.assertIs(stateMachine, self.tested)
        self.assertTrue(self.expectedSelfDestruct)
        self.expectedSelfDestruct = False

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

    def registerForInauguration(self, id, checkInCallback, doneCallback, progressCallback, failureCallback):
        self.assertEquals(id, self.hostImplementation.id())
        self.assertIs(self.checkInCallback, None)
        self.assertIs(self.doneCallback, None)
        self.checkInCallback = checkInCallback
        self.doneCallback = doneCallback
        self.progressCallback = progressCallback
        self.failureCallback = failureCallback

    def unregisterForInauguration(self, id):
        self.assertIsNot(self.checkInCallback, None)
        self.assertIsNot(self.doneCallback, None)
        self.assertIsNot(self.progressCallback, None)
        self.checkInCallback = None
        self.doneCallback = None
        self.progressCallback = None

    def assertRegisteredForInauguration(self, id):
        self.assertEquals(id, self.hostImplementation.id())
        self.assertIsNot(self.checkInCallback, None)
        self.assertIsNot(self.doneCallback, None)
        self.assertIsNot(self.progressCallback, None)

    def assertUnegisteredForInauguration(self, id):
        self.assertIs(self.checkInCallback, None)
        self.assertIs(self.doneCallback, None)
        self.assertIs(self.progressCallback, None)

    def provideLabelForInauguration(self, id, label):
        self.assertEquals(id, self.hostImplementation.id())
        if self.provideLabelRaises:
            raise Exception("Provide label raises on purpose, as part of test")
        self.actualProvidedLabel = label

    def isObjectInitialized(self):
        return hasattr(self, 'tested')

    def dnsmasqAddIfNotAlready(self, mac, ip):
        self.assertEquals(mac, self.hostImplementation.primaryMACAddress())
        self.assertEquals(ip, self.hostImplementation.ipAddress())
        self.assertTrue(self.expectedDnsmasqAddIfNotAlready)
        self.expectedDnsmasqAddIfNotAlready = False

    def reclaimHostCold(self, hostImplementation, reconfigureBIOS=False, hardReset=False):
        self.assertIs(hostImplementation, self.hostImplementation)
        self.assertTrue(self.expectedColdReclaim)
        self.expectedColdReclaim = False
        self.assertEqual(self.expectReconfigureBIOS, reconfigureBIOS)
        self.assertEqual(self.expectedHardReset, hardReset)

    def reclaimHostSoft(self, hostImplementation, isInauguratorActive=False, maxUptime=9999):
        self.assertIs(hostImplementation, self.hostImplementation)
        self.assertTrue(self.expectedSoftReclaim)
        self.expectedSoftReclaim = False
        self.softReclaimFailedCallback = self.tested.softReclaimFailed

    def validateProvidedLabel(self, expected):
        self.assertEquals(self.actualProvidedLabel, expected)
        self.expectedProvidedLabel = None

    def validateCheckInCallbackProvidesLabelImmediately(self, label):
        self.assertIn(self.tested.state(), [
            hoststatemachine.STATE_SOFT_RECLAMATION,
            hoststatemachine.STATE_COLD_RECLAMATION])
        self.assertIs(self.expectedProvidedLabel, None)
        self.expectedProvidedLabel = label
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.checkInCallback()
        self.validateProvidedLabel(expected=label)
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
        self.fakeTFTPBoot.expectToBeConfiguredForLocalBoot()
        self.doneCallback()
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.fakeTFTPBoot.validateConfiguredOnceForLocalBoot()
        self.assertIs(self.currentTimer, None)

    def inaugurationFailed(self, isLastAttemptBeforeRevertingToColdReclamation=False):
        self.assertIn(self.tested.state(), [hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED])
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        if isLastAttemptBeforeRevertingToColdReclamation:
            expectedReportedState = hoststatemachine.STATE_COLD_RECLAMATION
        else:
            expectedReportedState = hoststatemachine.STATE_SOFT_RECLAMATION
        self.expectedReportedState = expectedReportedState
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.expectedDnsmasqAddIfNotAlready = True
        self.expectedSoftReclaim = True
        self.failureCallback(message="Some osmosis failure")
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), expectedReportedState)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()

    def assign(self, label, hint):
        self.tested.assign(self.stateChangedCallback, label, hint)
        self.assertEquals(self.tested.imageLabel(), label)
        self.assertEquals(self.tested.imageHint(), hint)

    def test_vmLifeCycle_Normal(self):
        self.assertRegisteredForInauguration(self.hostImplementation.id())
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assign("fake image label", "fake image hint")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def unassignCausesSoftReclaim(self):
        self.assertFalse(self.expectedSoftReclaim)
        self.expectedSoftReclaim = True
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.expectedDnsmasqAddIfNotAlready = True
        self.tested.unassign()
        self.assertFalse(self.expectedSoftReclaim)
        self.assertFalse(self.expectedColdReclaim)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def validateCallCausesColdReclamation(self, call):
        self.assertFalse(self.expectedColdReclaim)
        self.expectedColdReclaim = True
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.expectedDnsmasqAddIfNotAlready = True
        call()
        self.assertFalse(self.expectedColdReclaim)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()
        self.assertFalse(self.expectedDnsmasqAddIfNotAlready)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def validateCallCausesSoftReclamation(self, call):
        self.assertFalse(self.expectedColdReclaim)
        self.expectedSoftReclaim = True
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.expectedDnsmasqAddIfNotAlready = True
        call()
        self.assertFalse(self.expectedSoftReclaim)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()
        self.assertFalse(self.expectedDnsmasqAddIfNotAlready)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def validateCallCausesReclamationAndStateReport(self, call, state):
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = state
        if state == hoststatemachine.STATE_COLD_RECLAMATION:
            self.validateCallCausesColdReclamation(call)
        elif state == hoststatemachine.STATE_SOFT_RECLAMATION:
            self.validateCallCausesSoftReclamation(call)
        else:
            self.assertFalse(True, state)
        self.assertIs(self.expectedReportedState, None)

    def validateCallCausesSoftReclamationAndStateReport(self, call):
        self.validateCallCausesReclamationAndStateReport(call, hoststatemachine.STATE_SOFT_RECLAMATION)

    def validateCallCausesColdReclamationAndStateReport(self, call):
        self.validateCallCausesReclamationAndStateReport(call, hoststatemachine.STATE_COLD_RECLAMATION)

    def test_vmLifeCycle_OrderlyRelease(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def test_vmLifeCycle_OrderlyRelease_QuickReclamationDidNotWork(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCallCausesColdReclamation(self.softReclaimFailedCallback)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def validateAssignCallbackProvidesLabelImmediately(self, label, hint):
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.assertIs(self.expectedProvidedLabel, None)
        self.expectedProvidedLabel = label
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.assign(label, hint)
        self.validateProvidedLabel(expected=label)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)

    def test_vmLifeCycle_Reuse_ReachedCheckeInBeforeReuse(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.checkInCallbackLingers()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.validateAssignCallbackProvidesLabelImmediately("fake image label 2", "fake image hint 2")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def test_vmLifeCycle_Reuse_ReassignedBeforeReachingCheckeIn(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assign("fake image label 2", "fake image hint 2")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label 2")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()

    def checkInCallbackLingers(self):
        self.assertIn(self.tested.state(), [
            hoststatemachine.STATE_SOFT_RECLAMATION,
            hoststatemachine.STATE_COLD_RECLAMATION])
        self.checkInCallback()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_CHECKED_IN)
        self.assertIs(self.currentTimer, None)

    def test_vmLifeCycle_QuickReclamationFailedWhenAssigned_UserDecidesToUnassign(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.assign("fake image label", "fake image hint")
        self.assertIsNot(self.softReclaimFailedCallback, None)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCallCausesColdReclamationAndStateReport(self.softReclaimFailedCallback)
        self.tested.unassign()
        self.checkInCallbackLingers()
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def test_vmLifeCycle_QuickReclamationFailedWithTimeoutWhenAssigned_UserDecidesToUnassign(self):
        self.assign("fake image label", "fake image hint")
        self.validateCallCausesColdReclamationAndStateReport(self.currentTimer)
        self.tested.unassign()
        self.checkInCallbackLingers()
        self.assertRegisteredForInauguration(self.hostImplementation.id())

    def test_coldReclamationSavesTheDay(self):
        self.validateCallCausesColdReclamation(self.currentTimer)
        self.checkInCallbackLingers()

    def validateTimerCausesSelfDestruct(self):
        self.assertFalse(self.expectedSelfDestruct)
        self.expectedSelfDestruct = True
        self.hostImplementation.expectedDestroy = True
        self.currentTimer()
        self.assertFalse(self.expectedSelfDestruct)
        self.assertFalse(self.hostImplementation.expectedDestroy)
        self.assertUnegisteredForInauguration(self.hostImplementation.id())

    def validateTimerCausesSelfDestructionAndStateReport(self):
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_DESTROYED
        self.validateTimerCausesSelfDestruct()
        self.assertIs(self.expectedReportedState, None)

    def validateDestructionOfHost(self, isAssigned):
        if isAssigned:
            validationMethod = self.validateCallCausesColdReclamationAndStateReport
        else:
            validationMethod = self.validateCallCausesColdReclamation
        klass = hoststatemachine.HostStateMachine
        for retryNr in range(1, klass.NR_CONSECUTIVE_ERRORS_BEFORE_DESTRUCTION + 1):
            if retryNr > klass.NR_CONSECUTIVE_ERRORS_BEFORE_HARD_RESET or retryNr == 1:
                self.expectedHardReset = True
            else:
                self.expectedHardReset = False
            if retryNr == klass.NR_CONSECUTIVE_ERRORS_BEFORE_CLEARING_DISK + 1:
                self.expectedClearDisk = True
            if retryNr == klass.NR_CONSECUTIVE_ERRORS_BEFORE_RECONFIGURING_BIOS + 1:
                self.expectReconfigureBIOS = True
            validationMethod(self.currentTimer)

    def validateTimeoutOnSoftReclamation(self, isLastAttemptBeforeRevertingToColdReclamation=False):
        self.expectedDnsmasqAddIfNotAlready = True
        self.expectedSoftReclaim = True
        if isLastAttemptBeforeRevertingToColdReclamation:
            expectedReportedState = hoststatemachine.STATE_COLD_RECLAMATION
        else:
            expectedReportedState = hoststatemachine.STATE_SOFT_RECLAMATION
        self.expectedReportedState = expectedReportedState
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.currentTimer()
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)
        self.assertEquals(self.tested.state(), expectedReportedState)
        self.fakeTFTPBoot.validateConfiguredOnceForInaugurator()

    def _reachMaxInaugurationFailureCountByFailureReports(self, imageLabel):
        failureCallback = self.inaugurationFailed
        self._reachMaxInaugurationFailureCount(imageLabel, failureCallback)

    def _reachMaxInaugurationFailureCountBySoftReclamationTimeouts(self, imageLabel):
        failureCallback = self.validateTimeoutOnSoftReclamation
        self._reachMaxInaugurationFailureCount(imageLabel, failureCallback)

    def _reachMaxInaugurationFailureCount(self, imageLabel, failureCallback):
        nrRetries = hoststatemachine.HostStateMachine.MAX_NR_CONSECUTIVE_INAUGURATION_FAILURES
        for _ in xrange(nrRetries):
            self.validateCheckInCallbackProvidesLabelImmediately(imageLabel)
            self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
            failureCallback()
            self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)

    def validateInaugurationDoneMessageReloadsSoftReclamationRetries(self, failureCallback):
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountByFailureReports("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.unassignCausesSoftReclaim()
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountByFailureReports("fake image label")

    def test_vmLifeCycle_AllReclamationRetriesFail_NoUser(self):
        self.validateDestructionOfHost(isAssigned=False)
        self.validateTimerCausesSelfDestruct()

    def test_vmLifeCycle_AllReclamationRetriesFail_WithUser(self):
        self.assign("fake image label", "fake image hint")
        self.validateDestructionOfHost(isAssigned=True)
        self.validateTimerCausesSelfDestructionAndStateReport()
        self.assertUnegisteredForInauguration(self.hostImplementation.id())

    def test_lateInaugurationDoneMessageDoesNotChangeState(self):
        self.assign("fake image label", "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.doneCallback()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)

    def test_checkInWhileNotReclaiming(self):
        label = "fake image label"
        self.assign(label, "fake image hint")
        self.validateCheckInCallbackProvidesLabelImmediately(label)
        self.assertIs(self.expectedReportedState, None)
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.assertIs(self.expectedProvidedLabel, None)
        self.checkInCallback()
        self.assertIs(self.expectedProvidedLabel, None)
        self.assertIs(self.expectedReportedState, None)

    def test_softReclamationFailureWhileDestroyedDoesNotChangeState(self):
        self.validateDestructionOfHost(isAssigned=False)
        self.validateTimerCausesSelfDestruct()
        self.assertUnegisteredForInauguration(self.hostImplementation.id())
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_DESTROYED)
        self.tested.softReclaimFailed()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_DESTROYED)

    def test_vmLifeCycle_notAFreshVM(self):
        self.currentTimer = None
        self.currentTimerTag = None
        self.checkInCallback = None
        self.doneCallback = None
        self.expectedDnsmasqAddIfNotAlready = True
        self.fakeTFTPBoot.expectToBeConfiguredForInaugurator()
        self.fakeDnsmasq.addIfNotAlready = mock.Mock()
        self.fakeTFTPBoot.configureForInaugurator = mock.Mock()
        self.expectedColdReclaim = True
        self.tested = hoststatemachine.HostStateMachine(
            hostImplementation=self.hostImplementation, inaugurate=self.fakeInaugurate,
            tftpboot=self.fakeTFTPBoot, dnsmasq=self.fakeDnsmasq, freshVMJustStarted=False,
            reclaimHost=self.fakeReclaimHost)
        self.tested.setDestroyCallback(self.destroyHost)
        self.assertIs(self.tested.hostImplementation(), self.hostImplementation)
        assert self.checkInCallback is not None
        assert self.doneCallback is not None
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)

    def test_vmLifeCycle_inauguratorProgress(self):
        self.assign("fake image label", "fake image hint")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.cancelAllTimersByTag(self.tested)
        self.progressCallback(dict(percent=100))
        self.assertIs(self.currentTimerTag, None)
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.cancelAllTimersByTag(self.tested)
        self.progressCallback(dict(percent=100))
        self.assertIs(self.currentTimerTag, None)
        self.progressCallback(dict(state='fetching', percent=100))
        self.assertIsNot(self.currentTimerTag, None)
        self.progressCallback(dict(state='whatisthisstate', percent=100))
        self.assertIsNot(self.currentTimerTag, None)
        self.inaugurationDone()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_DONE)
        self.cancelAllTimersByTag(self.tested)
        self.progressCallback(dict(percent=100))
        self.assertIs(self.currentTimerTag, None)
        self.unassignCausesSoftReclaim()
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCallCausesColdReclamation(self.softReclaimFailedCallback)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)
        self.cancelAllTimersByTag(self.tested)
        self.progressCallback(dict(percent=100))
        self.assertIs(self.currentTimerTag, None)
        self.checkInCallback()
        self.cancelAllTimersByTag(self.tested)
        self.progressCallback(dict(percent=100))
        self.assertIs(self.currentTimerTag, None)

    def test_clearingOfDiskNotAllowed(self):
        hoststatemachine.HostStateMachine.ALLOW_CLEARING_OF_DISK = False
        self.expectedClearDisk = False
        self.validateCallCausesColdReclamation(self.currentTimer)
        self.expectedHardReset = False
        self.validateCallCausesColdReclamation(self.currentTimer)
        self.validateCallCausesColdReclamation(self.currentTimer)
        self.expectedHardReset = True
        self.validateCallCausesColdReclamation(self.currentTimer)

    def test_timeoutWhenWaitingForInaugurationCausesSoftReclamation(self):
        self.assign("fake image label", "fake image hint")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_SOFT_RECLAMATION)
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED)
        self.validateCallCausesSoftReclamationAndStateReport(self.currentTimer)

    def test_failureDuringInaugurationCausesSoftReclamation(self):
        self.checkInCallback()
        self.expectedReportedState = hoststatemachine.STATE_INAUGURATION_LABEL_PROVIDED
        self.assign("fake image label", "fake image hint")
        self.inaugurationFailed()

    def test_revertToColdReclamationByExhaustingSoftReclamationsDueToInaugurationFailures(self):
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountByFailureReports("fake image label")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.expectedColdReclaim = True
        self.inaugurationFailed(isLastAttemptBeforeRevertingToColdReclamation=True)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)

    def test_revertToColdReclamationByExhaustingSoftReclamationsDueToTimeouts(self):
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountBySoftReclamationTimeouts("fake image label")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.expectedColdReclaim = True
        self.inaugurationFailed(isLastAttemptBeforeRevertingToColdReclamation=True)
        self.assertEquals(self.tested.state(), hoststatemachine.STATE_COLD_RECLAMATION)

    def test_coldReclamationBehavesNormallyAfterExhaustionOfSoftReclamationsDueToInaugurationFailures(self):
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountByFailureReports("fake image label")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.validateDestructionOfHost(isAssigned=True)

    def test_coldReclamationBehavesNormallyAfterExhaustionOfSoftReclamationsDueTimeouts(self):
        self.assign("fake image label", "fake image hint")
        self._reachMaxInaugurationFailureCountBySoftReclamationTimeouts("fake image label")
        self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
        self.validateDestructionOfHost(isAssigned=True)

    def test_unassigningDoesNotCauseDestruction(self):
        """This was created specifically to validate that allocations that are being stopped before the
        inauguration is either done, failed or timed out (could be a user manually stopping the
        allocation, or a timeout value smaller in the test client than in Rackattack), do not cause the
        state machine to be destroyed. To be destroyed, it has to either notify failure or timeout."""
        nrRetries = hoststatemachine.HostStateMachine.MAX_NR_CONSECUTIVE_INAUGURATION_FAILURES + \
            hoststatemachine.HostStateMachine.NR_CONSECUTIVE_ERRORS_BEFORE_DESTRUCTION + 20
        for _ in xrange(nrRetries):
            self.assign("fake image label", "fake image hint")
            self.validateCheckInCallbackProvidesLabelImmediately("fake image label")
            self.unassignCausesSoftReclaim()

    def test_InaugurationDoneMessageReloadsSoftReclamationRetriesAfterInaugurationFailureReports(self):
        def failureCallback():
            self._reachMaxInaugurationFailureCountByFailureReports("fake image label")
        self.validateInaugurationDoneMessageReloadsSoftReclamationRetries(failureCallback)

    def test_InaugurationDoneMessageReloadsSoftReclamationRetriesAfterSoftReclamationTimeouts(self):
        def failureCallback():
            self._reachMaxInaugurationFailureCountBySoftReclamationTimeouts("fake image label")
        self.validateInaugurationDoneMessageReloadsSoftReclamationRetries(failureCallback)

if __name__ == '__main__':
    unittest.main()
