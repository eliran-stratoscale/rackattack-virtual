import os
import mock
import base64
import logging
import unittest
import greenlet
from rackattack.common import reclaimhostspooler
from rackattack.common.hosts import Hosts
from rackattack.common.tests.epolleventloop_testcase import EpollEventLoopTestCase
from rackattack.common.tests.common import FakeHost, FakeTFTPBoot, FakeHostStateMachine


class ReclaimHostSpoolerWithColdReclamation(reclaimhostspooler.ReclaimHostSpooler):
    def __init__(self, *args, **kwargs):
        reclaimhostspooler.ReclaimHostSpooler.__init__(self, *args, **kwargs)


class Test(EpollEventLoopTestCase):
    def setUp(self):
        super(Test, self).setUp(moduleInWhichToSetupMocks=reclaimhostspooler)
        self._host = FakeHost()
        self._hostStateMachine = FakeHostStateMachine(self._host)
        self._hosts = Hosts()
        self._hosts.add(self._hostStateMachine)
        self._tftpboot = FakeTFTPBoot()
        self._wasThereAnAttemptToCreateFifo = False
        self._fakeSoftReclaimRequestFifoPath = "/fakeNotifyFifoPath"
        self._fakeSoftReclaimFailedFifoPath = "/fakeSoftReclaimFailedFifoPath"
        self._origKillSelf = reclaimhostspooler.suicide.killSelf
        reclaimhostspooler.suicide.killSelf = mock.Mock()
        self._actualColdReclamationRequests = []
        self._tested = self._generateTestedInstanceWithMockedThreading()
        self._expectedRequests = []
        self._coldReclaimCallbackRaisesException = False

    def tearDown(self):
        reclaimhostspooler.suicide.killSelf = self._origKillSelf
        super(Test, self).tearDown()

    def test_FifosCreatedIfDoNotExist(self):
        self.assertFalse(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertFalse(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))
        self._continueWithEventLoop()
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))

    def test_FifosStayIfAlreadyExist(self):
        self._pipeMethodsMock.osMkfifo(self._fakeSoftReclaimRequestFifoPath)
        self._pipeMethodsMock.osMkfifo(self._fakeSoftReclaimFailedFifoPath)
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))
        self._continueWithEventLoop()
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))

    def test_SoftReclaimRequest(self):
        self._validateSoftReclaimFlow()

    def test_SoftReclaimFailed(self):
        self._continueWithEventLoop()
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, self._host.id())
        self._continueWithEventLoop()
        self._hostStateMachine.softReclaimFailed.assert_called_once_with()

    def test_NoCrashOnSoftReclaimFailedCallbackFaliure(self):
        self._hostStateMachine.softReclaimFailed.side_effect = Exception("don't crash because of me")
        self._continueWithEventLoop()
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, self._host.id())
        self._continueWithEventLoop()
        self._hostStateMachine.softReclaimFailed.assert_called_once_with()
        self._hostStateMachine.softReclaimFailed.side_effect = None
        self._validateSoftReclaimFlow()

    def test_NoCrashOnSoftReclaimFailedMsgForNonExistentHost(self):
        self._continueWithEventLoop()
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, "non-existent")
        self._continueWithEventLoop()
        self._validateSoftReclaimFlow()

    def test_NoCrashOnSoftReclaimFailedForEmptyHost(self):
        self._continueWithEventLoop()
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, "fake id,,")
        self._continueWithEventLoop()
        self._validateSoftReclaimFlow()

    def test_SuicideOnFailure(self):
        self._continueWithEventLoop()
        self._addColdReclamationRequest(self._host)
        self._coldReclaimCallbackRaisesException = True
        self.assertRaises(ValueError, self._continueWithEventLoop)
        reclaimhostspooler.suicide.killSelf.assert_called_once_with()

    def test_NoCrashOnSoftReclaimRequestForHostWithEmptyName(self):
        self._host._id = ""
        self._validateSoftReclaimFlow()

    def test_ColdReclaimRequest(self):
        self._continueWithEventLoop()
        self._addColdReclamationRequest(self._host)
        self._continueWithEventLoop()
        self._validateExpectedRequests()

    def test_ColdReclaimRequestWithHardReset(self):
        self._continueWithEventLoop()
        self._addColdReclamationRequest(self._host, hardReset=True)
        self._continueWithEventLoop()
        self._validateExpectedRequests()

    def _addSoftReclamationRequest(self, host):
        self._expectedRequests.append(["soft", self._host])
        request = greenlet.greenlet(lambda: self._tested.soft(self._host))
        request.switch()

    def _addColdReclamationRequest(self, host, hardReset=False):
        self._expectedRequests.append(["cold", self._host, hardReset])
        request = greenlet.greenlet(lambda: self._tested.cold(self._host, hardReset=hardReset))
        request.switch()

    def _validateExpectedRequests(self):
        self._continueWithEventLoop()
        for request in self._expectedRequests:
            requestType = request[0]
            if requestType == "cold":
                actual = self._actualColdReclamationRequests.pop(0)
                expected = request[1:]
            elif requestType == "soft":
                host = request[1]
                expected = self._getEncodedSoftRequest(host)
                actual = self._pipeMethodsMock.getFifoContent(self._fakeSoftReclaimRequestFifoPath)
                actual = base64.decodestring(actual)
            else:
                self.assertFalse(True)
            self.assertEquals(actual, expected)

    def _validateSoftReclaimFlow(self):
        self._continueWithEventLoop()
        self._addSoftReclamationRequest(self._host)
        self._validateExpectedRequests()

    def _handleColdReclamationRequest(self, host, hardReset):
        if self._coldReclaimCallbackRaisesException:
            raise ValueError("Ignore me")
        self._actualColdReclamationRequests.append([host, hardReset])

    def _getEncodedColdRequest(self, host):
        requestArgs = [host.id(),
                       host.primaryMACAddress()]
        decodedRequest = ",".join(requestArgs)
        encodedRequest = base64.encodestring(decodedRequest)
        return encodedRequest

    def _getEncodedSoftRequest(self, host):
        credentials = host.rootSSHCredentials()
        requestArgs = ["soft",
                       host.id(),
                       credentials["hostname"],
                       credentials["username"],
                       credentials["password"],
                       host.primaryMACAddress(),
                       host.targetDevice(),
                       "False"]
        return ",".join(requestArgs)

    def _generateTestedInstance(self):
        ReclaimHostSpoolerWithColdReclamation._handleColdReclamationRequest =  \
            self._handleColdReclamationRequest
        instance = ReclaimHostSpoolerWithColdReclamation(self._hosts,
                                                         self._fakeSoftReclaimRequestFifoPath,
                                                         self._fakeSoftReclaimFailedFifoPath)
        return instance

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    streamHandler = logging.StreamHandler()
    streamHandler.setLevel(logging.INFO)
    logging.getLogger().addHandler(streamHandler)
    unittest.main()
