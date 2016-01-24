import os
import time
import socket
import logging
import threading
from rackattack.ssh import connection


logger = logging.getLogger("reclamation")


class UptimeTooLong(Exception):
    pass


class SoftReclaim(threading.Thread):
    _KEXEC_CMD = "kexec"

    def __init__(self,
                 hostID,
                 hostname,
                 username,
                 password,
                 macAddress,
                 targetDevice,
                 isInauguratorActive,
                 maxUptime,
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
        if targetDevice == "default":
            targetDevice = None
        self._targetDevice = targetDevice
        self._isInauguratorActive = isInauguratorActive == "True"
        self._maxUptime = maxUptime
        self._connection = None
        self.daemon = True
        threading.Thread.start(self)

    def run(self):
        if self._isInauguratorActive:
            self._softReclaimInaugurator()
        else:
            self._softReclaimBySSH()

    def _softReclaimInaugurator(self):
        logger.info("Attempting to reclaim inaugurator in %(hostID)s...", dict(hostID=self._hostID))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((self._hostname, 8888))
        except socket.timeout:
            logger.warn("Timeout while connecting to debug port in inaugurator of %(hostID)s",
                        dict(hostID=self._hostID))
        except Exception as ex:
            logger.warn("Could not connect to debug port in inaugurator of %(hostID)s: %(message)s",
                        dict(hostID=self._hostID, message=str(e)))
            return
        try:
            sock.send('reboot -f')
        except socket.timeout:
            logger.warn("Timeout while talking to debug port in inaugurator of %(hostID)s",
                        dict(hostID=self._hostID))
        except Exception as ex:
            logger.warn("Could not talk to debug port in inaugurator of %(hostID)s: %(message)s",
                        dict(hostID=self._hostID, message=str(e)))
            return

    def _softReclaimBySSH(self):
        self._connection = connection.Connection(hostname=self._hostname,
                                                 username=self._username,
                                                 password=self._password)
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
        maxUptime = int(self._maxUptime)
        logger.info("Host %(hostID)s uptime: %(uptime)s, max uptime: %(maxUptime)s",
                    dict(hostID=self._hostID, uptime=uptime, maxUptime=self._maxUptime))
        if uptime > maxUptime:
            raise UptimeTooLong(uptime)

    def _getUptime(self):
        uptimeContents = self._connection.ftp.getContents("/proc/uptime")
        uptimeSecondsPart = uptimeContents.split(" ")[0]
        uptime = float(uptimeSecondsPart)
        return uptime

    def _reclaimByKexec(self):
        self._connection.ftp.putFile("/tmp/vmlinuz", self._inauguratorKernel)
        self._connection.ftp.putFile("/tmp/initrd", self._inauguratorInitRD)
        self._connection.run.script(
            "%s --load /tmp/vmlinuz --initrd=/tmp/initrd --append='%s'" %
            (self._KEXEC_CMD,
             self._inauguratorCommandLine(self._hostID, self._macAddress, self._hostname, clearDisk=False,
                                          targetDevice=self._targetDevice)))
        self._connection.run.backgroundScript("sleep 2; %s -e" % (self._KEXEC_CMD,))

    def _sendSoftReclaimFailedMsg(self):
        msg = "%(hostID)s," % (dict(hostID=self._hostID))
        logger.info("Sending Soft-reclamation-failed message for '%(id)s'...", dict(id=self._hostID))
        os.write(self._softReclamationFailedMsgFifoWriteFd, msg)
        logger.info("Message sent for '%(id)s'.", dict(id=self._hostID))
