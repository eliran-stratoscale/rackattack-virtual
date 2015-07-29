import unittest
from rackattack.common.dnsmasq import DNSMasq
from mock import patch
import subprocess
import mock
from rackattack.common import tftpboot
import StringIO
import os
import signal
import contextlib
import fake_tempfile
import fake_filesystem
import fake_filesystem_glob
import fake_filesystem_shutil
import sys


@contextlib.contextmanager
def fakeFilesystem():
    fs = fake_filesystem.FakeFilesystem()
    fakeModules = dict(os=fake_filesystem.FakeOsModule(fs),
                       glob=fake_filesystem_glob.FakeGlobModule(fs),
                       path=fake_filesystem.FakePathModule(fs),
                       shutil=fake_filesystem_shutil.FakeShutilModule(fs),
                       tempfile=fake_tempfile.FakeTempfileModule(fs))
    fakeFunctions = dict(open=fake_filesystem.FakeFileOpen(fs))
    originals = dict()
    for moduleName, fakeModule in fakeModules.iteritems():
        __import__(moduleName)
        originals[moduleName] = sys.modules[moduleName]
        globals()[moduleName] = fakeModule
    for functionName, fakeFunction in fakeFunctions.iteritems():
        originals[functionName] = sys.modules[moduleName]
        globals()[functionName] = fakeFunction
    yield fs
    for moduleName, module in originals.iteritems():
        globals()[moduleName] = originals[moduleName]
    for functionName, function in originals.iteritems():
        globals()[functionName] = originals[functionName]


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

    def test_addRemove(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')
        os.kill.reset_mock()
        self.tested.remove('11:22:33:44:55:66')
        os.kill.assert_called_once_with(12345, signal.SIGHUP)
        self.assertEquals(self.tested._hostsFile.getvalue(), '11:22:33:44:55:67,10.0.0.4,infinite')

    def test_addIfNotAlready(self, *args):
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.tested._hostsFile.getvalue(), '')
        self.tested.addIfNotAlready('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite')

    def test_addRemoveTwice(self, *args):
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.tested.add('11:22:33:44:55:67', '10.0.0.4')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:66,10.0.0.3,infinite\n11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.tested._hostsFile.getvalue(), '11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.remove('11:22:33:44:55:66')
        self.assertEquals(self.tested._hostsFile.getvalue(), '11:22:33:44:55:67,10.0.0.4,infinite')
        self.tested.add('11:22:33:44:55:66', '10.0.0.3')
        self.assertEquals(self.tested._hostsFile.getvalue(),
                          '11:22:33:44:55:67,10.0.0.4,infinite\n11:22:33:44:55:66,10.0.0.3,infinite')

    def test_eraseLeasesFile(self, *args):
        LEASES_FILE = "/var/lib/dnsmasq/dnsmasq.leases"
        with fakeFilesystem() as fs:
            fs.CreateFile(LEASES_FILE, create_missing_dirs=True)
            import pdb; pdb.set_trace()
            self.tested.eraseLeasesFile()
            self.assertFalse(fs.Exists(LEASES_FILE))


if __name__ == '__main__':
    unittest.main()
