import mock
import select
import greenlet
import unittest
import threading
from rackattack.common.tests.fakeepoll import FakeEpoll


class EpollEventLoopTestCase(unittest.TestCase):
    def setUp(self):
        super(EpollEventLoopTestCase, self).setUp()
        self._poller = None
        self._origPoll = None

    def _continueWithEventLoop(self):
        events = self._origPoll()
        if events:
            self._testedServerContext.switch(events)
        else:
            self._testedServerContext.switch()

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
        self._origPoll = self._poller.poll
        self._poller.poll = self._selectEpollPollWrapper
        return self._poller

    def _generateTestedInstanceWithMockedThreading(self):
        self._origThreadInit = threading.Thread.__init__
        origThreadStart = threading.Thread.start
        origSelectEpoll = select.epoll
        self._threads = set()
        try:
            threading.Thread.__init__ = self._threadInitRegisterThreadWrapper
            threading.Thread.start = mock.Mock()
            select.epoll = self._selectEpollWrapper
            instance = self._generateTestedInstance()
        finally:
            threading.Thread.__init__ = self._origThreadInit
            threading.Thread.start = origThreadStart
            select.epoll = origSelectEpoll
        assert len(self._threads) == 1
        thread = self._threads.pop()
        self._testedServerContext = greenlet.greenlet(thread.run)
        assert self._poller is not None
        return instance
