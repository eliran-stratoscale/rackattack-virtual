import os
import mock
import base64
import logging
import unittest
import greenlet
from rackattack.common import reclaimhost
from rackattack.common.hosts import Hosts
from rackattack.common.tests import mockpipes
from rackattack.common.tests import mockfilesystem
from rackattack.common.tests.epolleventloop_testcase import EpollEventLoopTestCase
from rackattack.common.tests.common import FakeHost, FakeTFTPBoot, FakeHostStateMachine


class ReclaimHostTest(EpollEventLoopTestCase):
    def setUp(self):
        super(ReclaimHostTest, self).setUp()
        self._host = FakeHost()
        self._hostStateMachine = FakeHostStateMachine(self._host)
        self._hosts = Hosts()
        self._hosts.add(self._hostStateMachine)
        self._tftpboot = FakeTFTPBoot()
        self._wasThereAnAttemptToCreateFifo = False
        self._fakeFilesystem = mockfilesystem.enableMockedFilesystem(reclaimhost)
        self._pipeMethodsMock = mockpipes.enable(reclaimhost, self._fakeFilesystem)
        self._fakeSoftReclaimRequestFifoPath = "fakeNotifyFifoPath"
        self._fakeSoftReclaimFailedFifoPath = "fakeSoftReclaimFailedFifoPath"

    def tearDown(self):
        mockpipes.disable(reclaimhost)
        mockfilesystem.disableMockedFilesystem(reclaimhost)

    def _validateSoftReclamationRequestsFifo(self, requests):
        for requestType, host in requests:
            if requestType == "soft":
                expectedRequest = self._getEncodedSoftRequest(host)
            elif requestType == "cold":
                expectedRequest = self._getEncodedColdRequest(host)
            else:
                self.assertTrue(False)
            actual = self._pipeMethodsMock.getFifoContent(self._fakeSoftReclaimRequestFifoPath)
            expected = expectedRequest + ","
            self.assertEquals(actual, expected)

    def _getEncodedColdRequest(self, host):
        requestArgs = [host.id(),
                       host.primaryMacAddress()]
        decodedRequest = ",".join(requestArgs)
        encodedRequest = base64.encodestring(decodedRequest)
        return encodedRequest

    def _getEncodedSoftRequest(self, host):
        credentials = host.rootSSHCredentials()
        requestArgs = [host.id(),
                       credentials["hostname"],
                       credentials["username"],
                       credentials["password"],
                       host.primaryMacAddress()]
        decodedRequest = ",".join(requestArgs)
        encodedRequest = base64.encodestring(decodedRequest)
        return encodedRequest

    def _generateTestedInstance(self):
        instance = reclaimhost.ReclaimHostSpooler(self._hosts,
                                                  self._fakeSoftReclaimRequestFifoPath,
                                                  self._fakeSoftReclaimFailedFifoPath)
        instance._handleColdReclamationRequest = mock.Mock()
        return instance


class Test(ReclaimHostTest):
    def setUp(self):
        super(Test, self).setUp()
        self._tested = None
        self._expectedRequests = []

    def test_FifosCreatedIfDoNotExist(self):
        self._generateTestedInstanceWithMockedThreading()
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))

    def test_FifosStayIfAlreadyExist(self):
        self._pipeMethodsMock.osMkfifo(self._fakeSoftReclaimRequestFifoPath)
        self._pipeMethodsMock.osMkfifo(self._fakeSoftReclaimFailedFifoPath)
        self._generateTestedInstanceWithMockedThreading()
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimRequestFifoPath))
        self.assertTrue(self._fakeFilesystem.Exists(self._fakeSoftReclaimFailedFifoPath))

    def test_SoftReclaimRequest(self):
        self._validateSoftReclaimFlow()

    def test_SoftReclaimFailed(self):
        self._validateSoftReclaimFlow()
        fifo = self._pipeMethodsMock.getFifoByFilename(self._fakeSoftReclaimFailedFifoPath)
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, self._host.id())
        self._continueWithEventLoop()
        self._hostStateMachine.softReclaimFailed.assert_called_once_with()

    def test_SpoolerDoesNotCrashOnFaultySoftReclaimFailedMessage(self):
        self._validateSoftReclaimFlow()
        fifo = self._pipeMethodsMock.getFifoByFilename(self._fakeSoftReclaimFailedFifoPath)
        softReclaimFailedFifoWriteFd = self._pipeMethodsMock.osOpen(self._fakeSoftReclaimFailedFifoPath,
                                                                    os.O_WRONLY)
        self._pipeMethodsMock.osWrite(softReclaimFailedFifoWriteFd, "non existent")
        self._continueWithEventLoop()
        self._validateSoftReclaimFlow()

    def test_ColdReclaimRequest(self):
        self._validateColdReclaimFlow()

    def _addSoftReclamationRequest(self, host):
        self._expectedRequests.append(["soft", self._host])
        request = greenlet.greenlet(lambda: self._tested.soft(self._host))
        request.switch()

    def _addColdReclamationRequest(self, host):
        self._expectedRequests.append(["cold", self._host])
        request = greenlet.greenlet(lambda: self._tested.cold(self._host))
        request.switch()

    def _handleSoftReclamationRequest(self):
        self._continueWithEventLoop()
        self._expectedRequests.pop(0)
        self._validateSoftReclamationRequestsFifo(self._expectedRequests)

    def _handleColdReclamationRequest(self):
        self._continueWithEventLoop()
        self._expectedRequests.pop(0)
        self._tested._handleColdReclamationRequest.assert_called_once_with(host=self._host)

    def _makeSureEventLoopStarts(self):
        if self._tested is None:
            self._tested = self._generateTestedInstanceWithMockedThreading()
        self._continueWithEventLoop()

    def _validateSoftReclaimFlow(self):
        self._makeSureEventLoopStarts()
        self._addSoftReclamationRequest(self._host)
        self._handleSoftReclamationRequest()

    def _validateColdReclaimFlow(self):
        self._makeSureEventLoopStarts()
        self._addColdReclamationRequest(self._host)
        self._handleColdReclamationRequest()

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    streamHandler = logging.StreamHandler()
    streamHandler.setLevel(logging.INFO)
    logging.getLogger().addHandler(streamHandler)
    unittest.main()
