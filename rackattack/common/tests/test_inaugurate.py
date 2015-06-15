import os
import sys
import mock
import unittest
import inaugurator
import rackattack.common.inaugurate
from rackattack.common import globallock


class Test(unittest.TestCase):
    def setUp(self):
        inaugurator.server.rabbitmqwrapper.RabbitMQWrapper = mock.Mock()
        inaugurator.server.server.Server = mock.Mock()
        self.tested = rackattack.common.inaugurate.Inaugurate(None)
        self.tested._server.provideLabel = mock.Mock()
        self.checkIn = mock.Mock()
        self.done = mock.Mock()
        self.progress = mock.Mock()

    def test_register(self):
        with globallock.lock():
            self.tested.register('awesome-server', self.checkIn, self.done, self.progress)
        self.assertEquals(self.checkIn.call_count, 0)
        self.assertEquals(self.done.call_count, 0)
        self.assertEquals(self.progress.call_count, 0)
        self.tested._checkIn('awesome-server')
        self.tested._checkIn('non-awesome-server')
        self.checkIn.assert_called_once_with()
        self.tested._done('awesome-server')
        self.tested._done('non-awesome-server')
        self.done.assert_called_once_with()
        self.tested._progress('awesome-server', 'some progress')
        self.tested._progress('non-awesome-server', 'some other progress')
        self.progress.assert_called_once_with('some progress')
        with globallock.lock():
            self.assertRaises(AssertionError, self.tested.register, 'awesome-server', None, None, None)
        self.done.assert_called_once_with()
        self.progress.assert_called_once_with('some progress')

    def test_filterDigesting(self):
        with globallock.lock():
            self.tested.register('awesome-server', self.checkIn, self.done, self.progress)
        self.tested._progress('awesome-server', dict(state='digesting'))
        self.assertEquals(self.progress.call_count, 0)

    def test_unregister(self):
        with globallock.lock():
            self.tested.register('awesome-server', self.checkIn, self.done, self.progress)
        self.assertEquals(self.checkIn.call_count, 0)
        self.tested._checkIn('awesome-server')
        self.checkIn.assert_called_once_with()
        with globallock.lock():
            self.tested.unregister('awesome-server')
        self.checkIn.assert_called_once_with()
        self.tested._checkIn('awesome-server')
        self.checkIn.assert_called_once_with()
        with globallock.lock():
            self.assertRaises(AssertionError, self.tested.unregister, 'awesome-server')

    def test_provideLabel(self):
        self.tested.provideLabel('awesome-server', 'awesome-label')
        self.tested._server.provideLabel.assert_called_once_with(id='awesome-server',
                                                                 label='awesome-label')


if __name__ == '__main__':
    unittest.main()
