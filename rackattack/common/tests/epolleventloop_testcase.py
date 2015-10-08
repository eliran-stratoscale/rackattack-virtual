import mock
import select
import greenlet
import unittest
import threading
from rackattack.common.tests import mockpipes
from rackattack.common.tests import mockfilesystem
from rackattack.common.tests.fakeepoll import FakeEpoll


class EpollEventLoopTestCase(unittest.TestCase):
    def setUp(self, moduleInWhichToSetupMocks):
        super(EpollEventLoopTestCase, self).setUp()
        self._moduleInWhichToSetupMocks = moduleInWhichToSetupMocks
        self._fakeFilesystem = mockfilesystem.enableMockedFilesystem(self._moduleInWhichToSetupMocks)
        self._pipeMethodsMock = mockpipes.enable(self._moduleInWhichToSetupMocks, self._fakeFilesystem)
        self._moduleInWhichToSetupMocks.select.epoll = self._selectEpollWrapper
        self._poller = None
        self._origPollerPoll = None

    def tearDown(self):
        mockpipes.disable(self._moduleInWhichToSetupMocks)
        mockfilesystem.disableMockedFilesystem(self._moduleInWhichToSetupMocks)
        super(EpollEventLoopTestCase, self).tearDown()

    def _continueWithEventLoop(self):
        if self._poller is None:
            self._testedServerContext.switch()
        else:
            events = self._origPollerPoll()
            self._testedServerContext.switch(events)

    def _generateTestedInstance(self):
        raise NotImplementedError

    def _threadInitRegisterThreadWrapper(self, *args, **kwargs):
        self._origThreadInit(*args, **kwargs)
        threadInstance = args[0]
        self._threads.add(threadInstance)

    def _selectEpollPollWrapper(self):
        events = greenlet.getcurrent().parent.switch()
        return events

    def _selectEpollWrapper(self):
        assert self._poller is None
        self._poller = FakeEpoll(self._pipeMethodsMock)
        self._origPollerPoll = self._poller.poll
        self._poller.poll = self._selectEpollPollWrapper
        return self._poller

    def _generateTestedInstanceWithMockedThreading(self):
        self._origThreadInit = threading.Thread.__init__
        origThreadStart = threading.Thread.start
        origSelectEpoll = select.epoll
        self._threads = set()
        try:
            self._moduleInWhichToSetupMocks.threading.Thread.__init__ = \
                self._threadInitRegisterThreadWrapper
            self._moduleInWhichToSetupMocks.threading.Thread.daemon = mock.Mock()
            self._moduleInWhichToSetupMocks.threading.Event = mock.Mock()
            threading.Thread.start = mock.Mock()
            instance = self._generateTestedInstance()
        finally:
            threading.Thread.__init__ = self._origThreadInit
            threading.Thread.start = origThreadStart
            select.epoll = origSelectEpoll
        assert len(self._threads) == 1
        thread = self._threads.pop()
        self._testedServerContext = greenlet.greenlet(thread.run)
        return instance
