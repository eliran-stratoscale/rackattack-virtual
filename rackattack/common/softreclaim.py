import os
import time
import logging
import threading
from rackattack.ssh import connection


logger = logging.getLogger("reclamation")


class UptimeTooLong(Exception):
    pass


class SoftReclaim(threading.Thread):
    _AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN = 60 * 60 * 24
    _KEXEC_CMD = "kexec"
    _INAUGURATOR_DIRPATH = "/var/lib/inaugurator"

    def __init__(self,
                 hostID,
                 hostname,
                 username,
                 password,
                 macAddress,
                 inauguratorCommandLine,
                 softReclamationFailedMsgFifoWriteFd,
                 inauguratorKernel,
                 inauguratorInitRD):
        threading.Thread.__init__(self)
        self._inauguratorCommandLine = inauguratorCommandLine
        self._softReclamationFailedMsgFifoWriteFd = softReclamationFailedMsgFifoWriteFd
        self._inauguratorKernel = inauguratorKernel
        self._inauguratorInitRD = inauguratorInitRD
        self._hostID = hostID
        self._hostname = hostname
        self._username = username
        self._password = password
        self._macAddress = macAddress
        self._connection = connection.Connection(hostname=self._hostname,
                                                 username=self._username,
                                                 password=self._password)
        self._inauguratorKernelPath = os.path.join(self._INAUGURATOR_DIRPATH, "vmlinuz")
        self._inauguratorInitRDPath = os.path.join(self._INAUGURATOR_DIRPATH, "initrd")
        self.daemon = True
        threading.Thread.start(self)

    def run(self):
        try:
            self._connection.connect()
        except:
            logger.info("Unable to connect by ssh to '%(id)s'.", dict(id=self._hostID))
            self._sendSoftReclaimFailedMsg()
            return
        try:
            self._validateUptime()
            self._reclaimByKexec()
        except UptimeTooLong as e:
            logger.error("System '%(id)s' is up for too long: %(uptime)s. Will not kexec.",
                         dict(id=self._hostID, uptime=e.args[0]))
            self._sendSoftReclaimFailedMsg()
        except Exception as e:
            logger.error("An error has occurred during soft reclamation of '%(id)s': %(message)s",
                         dict(id=self._hostID, message=e.message))
            self._sendSoftReclaimFailedMsg()
        finally:
            self._tryToCloseConnection()

    def _tryToCloseConnection(self):
        try:
            self._connection.close()
        except Exception as e:
            logger.error("Unable to close connection to '%(id)s': '%(message)s.'",
                         dict(id=self._hostID, message=e.message))

    def _validateUptime(self):
        uptime = self._getUptime()
        if uptime > self._AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN:
            raise UptimeTooLong(uptime)

    def _getUptime(self):
        uptimeContents = self._connection.ftp.getContents("/proc/uptime")
        uptimeSecondsPart = uptimeContents.split(" ")[0]
        uptime = float(uptimeSecondsPart)
        return uptime

    def _reclaimByKexec(self):
        try:
            print self._connection.run.script("ls %(inauguratorKernelPath)s %(inauguratorInitRDPath)s" %
                                            dict(inauguratorKernelPath=self._inauguratorKernelPath,
                                                 inauguratorInitRDPath=self._inauguratorInitRDPath))
            raise ValueError()
            logger.info("Host %(hostID)s has the inaugurator image in its cache", dict(hostID=self._hostID))
        except:
            logger.info("Transferring inaugurator to %(hostID)s by FTP", dict(hostID=self._hostID))
            print self._connection.run.script("mkdir -p %s" % (self._INAUGURATOR_DIRPATH,))
            print self._connection.ftp.putContents(self._inauguratorKernelPath, self._inauguratorKernel)
            print self._connection.ftp.putContents(self._inauguratorInitRDPath, self._inauguratorInitRD)
            logger.info("Done transferring inaugurator to %(hostID)s by FTP.", dict(hostID=self._hostID))
        self._connection.run.script(
            "%s --load %s --initrd=%s --append='%s'" %
            (self._KEXEC_CMD,
             self._inauguratorKernelPath,
             self._inauguratorInitRDPath,
             self._inauguratorCommandLine(self._hostID, self._macAddress, self._hostname, clearDisk=False)))
        self._connection.run.backgroundScript("sleep 2; %s -e" % (self._KEXEC_CMD,))

    def _sendSoftReclaimFailedMsg(self):
        msg = "%(hostID)s," % (dict(hostID=self._hostID))
        logger.info("Sending Soft-reclamation-failed message for '%(id)s'...", dict(id=self._hostID))
        os.write(self._softReclamationFailedMsgFifoWriteFd, msg)
        logger.info("Message sent for '%(id)s'.", dict(id=self._hostID))
