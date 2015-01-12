import unittest
from rackattack.common.dnsmasq import DNSMasq
from mock import patch
import subprocess
import mock
from rackattack.common import tftpboot
import StringIO
import os
import signal


@patch('os.kill')
class Test(unittest.TestCase):

    def setUp(self):
        subprocess.Popen = mock.MagicMock(spec=subprocess.Popen)
        self.tftpBootMock = mock.Mock(tftpboot.TFTPBoot)
        DNSMasq.run = lambda x: None
        self.tested = DNSMasq(self.tftpBootMock, '10.0.0.1', '255.255.255.0', '10.0.0.2', '10.0.0.10',
                              gateway='10.0.0.20', nameserver='8.8.8.8', interface='eth0')
        self.tested._popen.pid = 12345
        self.tested._hostsFile = StringIO.StringIO()

    def test_addHost(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        os.kill.reset_mock()
        self.assertEquals(self.tested._hostsFile.getvalue(), '11:22:33:44:55:66,10.0.0.3,infinite')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')

    def test_addDelete(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')
        os.kill.reset_mock()
        self.tested.remove('11:22:33:44:55:66')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        self.assertEquals(self.tested._hostsFile.getvalue(), '11:22:33:44:55:67,10.0.0.4,infinite')


if __name__ == '__main__':
    unittest.main()
