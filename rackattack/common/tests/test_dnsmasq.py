import unittest
from rackattack.common.dnsmasq import DNSMasq
from mock import patch
import subprocess
import mock
from rackattack.common import tftpboot
import rackattack
import os
import signal
from rackattack.common.tests.mockfilesystem import enableMockedFilesystem, disableMockedFilesystem


@patch('os.kill')
class Test(unittest.TestCase):

    def setUp(self):
        self.fakeFilesystem = enableMockedFilesystem(rackattack.common.dnsmasq)
        self.fakeFilesystem.CreateDirectory("/tmp")
        self.fakeFilesystem.CreateFile(DNSMasq.LEASES_FILE, create_missing_dirs=True)
        subprocess.Popen = mock.MagicMock(spec=subprocess.Popen)
        self.tftpBootMock = mock.Mock(tftpboot.TFTPBoot)
        DNSMasq.run = lambda x: None
        self.tested = DNSMasq(self.tftpBootMock, '10.0.0.1', '255.255.255.0', '10.0.0.2', '10.0.0.10',
                              gateway='10.0.0.20', nameserver='8.8.8.8', interface='eth0')
        self.tested._popen = subprocess.Popen()
        self.tested._popen.pid = 12345

    def tearDown(self):
        disableMockedFilesystem(rackattack.common.dnsmasq)

    def test_addHost(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        os.kill.reset_mock()
        self.assertEquals(self.getHostsFileContents(), '11:22:33:44:55:66,10.0.0.3,infinite')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')

    def test_addRemove(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')
        os.kill.reset_mock()
        self.tested.remove('11:22:33:44:55:66')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        self.assertEquals(self.getHostsFileContents(), '11:22:33:44:55:67,10.0.0.4,infinite')

    def test_addIfNotAlready(self, *args):
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:66,10.0.0.3,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.getHostsFileContents(), '')
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:66,10.0.0.3,infinite')

    def test_addRemoveTwice(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.getHostsFileContents(), '11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.getHostsFileContents(), '11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.getHostsFileContents(),
                          '11:22:33:44:55:67,10.0.0.4,infinite\n11:22:33:44:55:66,10.0.0.3,infinite')

    def test_eraseLeasesFile(self, *args):
        self.assertTrue(self.fakeFilesystem.Exists(DNSMasq.LEASES_FILE))
        self.tested.eraseLeasesFile()
        self.assertFalse(self.fakeFilesystem.Exists(DNSMasq.LEASES_FILE))

    def getHostsFileContents(self):
        return self.fakeFilesystem.GetObject(DNSMasq.HOSTS_FILENAME).contents


if __name__ == '__main__':
    unittest.main()
