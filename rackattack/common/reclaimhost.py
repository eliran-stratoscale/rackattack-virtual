import threading
import logging
import time
from rackattack.ssh import connection
from rackattack.common import tftpboot
from rackattack.common import globallock


class ReclaimHost(threading.Thread):
    @classmethod
    def cold(cls, hostImplementation, tftpboot, reconfigureBIOS=False):
        cls(cold=True, hostImplementation=hostImplementation,
            tftpboot=tftpboot, softReclaimFailedCallback=None, reconfigureBIOS=reconfigureBIOS)

    @classmethod
    def soft(cls, hostImplementation, tftpboot, failedCallback):
        cls(
            cold=False, hostImplementation=hostImplementation,
            tftpboot=tftpboot, softReclaimFailedCallback=failedCallback)

    _AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN = 60 * 60 * 24
    _COLD_RESTART_RETRIES = 5
    _COLD_RESTART_RETRY_INTERVAL = 10

    def __init__(self, cold, hostImplementation, tftpboot, softReclaimFailedCallback, reconfigureBIOS=False):
        self._cold = cold
        self._hostImplementation = hostImplementation
        self._tftpboot = tftpboot
        self._reconfigureBIOS = reconfigureBIOS
        assert cold and softReclaimFailedCallback is None or \
            not cold and softReclaimFailedCallback is not None
        self._softReclaimFailedCallback = softReclaimFailedCallback
        threading.Thread.__init__(self)
        self.daemon = True
        threading.Thread.start(self)

    def run(self):
        if self._cold:
            self._coldRestart()
        else:
            try:
                self._reclaimByKexec()
            except:
                logging.exception("Unable to reclaim by kexec '%(id)s'", dict(
                    id=self._hostImplementation.id()))
                assert self._softReclaimFailedCallback is not None
                with globallock.lock():
                    self._softReclaimFailedCallback()

    def _coldRestart(self):
        if self._reconfigureBIOS:
            self._hostImplementation.reconfigureBIOS()
        for retry in xrange(self._COLD_RESTART_RETRIES):
            try:
                self._hostImplementation.coldRestart()
                return
            except:
                logging.exception("Unable to reclaim by cold restart '%(id)s'", dict(
                    id=self._hostImplementation.id()))
                time.sleep(self._COLD_RESTART_RETRY_INTERVAL)
        raise Exception("Cold restart retries exceeded '%(id)s'" % dict(
            id=self._hostImplementation.id()))

    def _reclaimByKexec(self):
        ssh = connection.Connection(**self._hostImplementation.rootSSHCredentials())
        ssh.connect()
        uptime = float(ssh.ftp.getContents("/proc/uptime").split(" ")[0])
        if uptime > self._AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN:
            raise Exception(
                "system '%(id)s' is up for way too long, will not kexec. doing cold restart" % dict(
                    id=self._hostImplementation.id()))
        try:
            ssh.run.script("kexec -h")
        except:
            raise Exception("kexec does not exist on image on '%(id)s', reverting to cold restart" % dict(
                id=self._hostImplementation.id()))
        ssh.ftp.putFile("/tmp/vmlinuz", tftpboot.INAUGURATOR_KERNEL)
        ssh.ftp.putFile("/tmp/initrd", tftpboot.INAUGURATOR_INITRD)
        ssh.run.script(
            "kexec --load /tmp/vmlinuz --initrd=/tmp/initrd --append='%s'" %
            self._tftpboot.inauguratorCommandLine(
                self._hostImplementation.primaryMACAddress(), self._hostImplementation.ipAddress(),
                clearDisk=False))
        ssh.run.backgroundScript("sleep 2; kexec -e")
