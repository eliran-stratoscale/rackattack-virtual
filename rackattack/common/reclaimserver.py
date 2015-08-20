import os
import time
import base64
import select
import logging
import argparse
import threading
import functools
from rackattack.ssh import connection
from rackattack.common import tftpboot


logger = logging.getLogger("reclamation")


class UptimeTooLong(Exception):
    pass


class KexecDoesNotExistOnHost(Exception):
    pass


class SoftReclaim(threading.Thread):
    _AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN = 60 * 60 * 24
    _KEXEC_CMD = "kexec"

    def __init__(self,
                 hostID,
                 hostname,
                 username,
                 password,
                 macAddress,
                 inauguratorCommandLine,
                 softReclamationFailedMsgFifoWriteFd):
        threading.Thread.__init__(self)
        self._inauguratorCommandLine = inauguratorCommandLine
        self._softReclamationFailedMsgFifoWriteFd = softReclamationFailedMsgFifoWriteFd
        self._hostID = hostID
        self._hostname = hostname
        self._username = username
        self._password = password
        self._macAddress = macAddress
        self._connection = connection.Connection(hostname=self._hostname,
                                                 username=self._username,
                                                 password=self._password)
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
        except KexecDoesNotExistOnHost:
            logger.error("kexec does not exist on image on '%(id)s', reverting to cold restart",
                          dict(id=self._hostID))
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
            self._connection.run.script("echo -h")
        except:
            raise KexecDoesNotExistOnHost()
        self._connection.ftp.putFile("/tmp/vmlinuz", tftpboot.INAUGURATOR_KERNEL)
        self._connection.ftp.putFile("/tmp/initrd", tftpboot.INAUGURATOR_INITRD)
        self._connection.run.script(
            "%s --load /tmp/vmlinuz --initrd=/tmp/initrd --append='%s'" %
            (self._KEXEC_CMD,
             self._inauguratorCommandLine(self._hostID, self._macAddress, self._hostname, clearDisk=False)))
        self._connection.run.backgroundScript("sleep 2; %s -e" % (self._KEXEC_CMD,))

    def _sendSoftReclaimFailedMsg(self):
        msg = "%(hostID)s," % (dict(hostID=self._hostID))
        logger.info("Sending Soft-reclamation-failed message for '%(id)s'...", dict(id=self._hostID))
        os.write(self._softReclamationFailedMsgFifoWriteFd, msg)
        logger.info("Message sent for '%(id)s'.", dict(id=self._hostID))


class ThreadsMonitor(threading.Thread):
    INTERVAL = 4

    def __init__(self):
        threading.Thread.__init__(self)
        self._lock = threading.Lock()
        self._threads = set()
        self.start()

    def add(self, _thread):
        with self._lock:
            self._refreshSetOfRunningThreads()
            self._threads.add(_thread)
        nrThreads = len(self._threads)
        logger.info("Currently running %(nrThreads)s threads.", dict(nrThreads=nrThreads))

    def _refreshSetOfRunningThreads(self):
        assert self._lock.locked()
        self._threads = set([_thread for _thread in self._threads if _thread.isAlive()])

    def run(self):
        while True:
            time.sleep(self.INTERVAL)
            with self._lock:
                self._refreshSetOfRunningThreads()
            nrThreads = len(self._threads)
            logger.info("Currently running %(nrThreads)s threads.", dict(nrThreads=nrThreads))


class InvalidRequest(Exception):
    pass


class IOLoop:
    # A large buffer size is needed to avoid the need for reassembly of chunks read from the pipe.
    _BUF_SIZE = 1024 ** 2

    def __init__(self, inauguratorCommandLine, reclamationRequestFifoPath, softReclamationFailedMsgFifoPath):
        self._reclamationRequestFifoPath = reclamationRequestFifoPath
        self._softReclamationFailedMsgFifoPath = softReclamationFailedMsgFifoPath
        self._monitor = ThreadsMonitor()
        self._requestsReadFd = None
        self._softReclamationFailedMsgFifoWriteFd = None
        self._validateFifosExist()
        self._openFifos()
        self._actionTypes = dict(soft=functools.partial(
            SoftReclaim,
            inauguratorCommandLine=inauguratorCommandLine,
            softReclamationFailedMsgFifoWriteFd=self._softReclamationFailedMsgFifoWriteFd))

    def registerAction(self, _type, callback):
        assert _type not in self._actionTypes
        self._actionTypes[_type] = callback

    def run(self):
        while True:
            logger.info("Waiting for requests...")
            requests = self._readRequestsFromPipe()
            for actionType, args in requests:
                self._executeRequest(actionType, args)
        self._cleanup()

    def _decodeRequest(self, request):
        try:
            request = base64.decodestring(request)
            if not request:
                raise ValueError(request)
        except:
            logger.error("Could not decode request's base64: %(request)s", dict(request=request))
            raise InvalidRequest(request)
        request = request.split(",")
        try:
            actionType = request[0]
            args = request[1:]
        except KeyError:
            logger.warn("Invalid fields in request %(request)s", dict(request=str(request)))
            raise InvalidRequest(request)
        if actionType not in self._actionTypes:
            logger.warn("Invalid request type: %(actionType)s. Ignoring.", dict(actionType=actionType))
            raise InvalidRequest(request)
        return actionType, args

    def _decodeRequests(self, encodedRequests):
        encodedRequests = encodedRequests.split(",")
        for encodedRequest in encodedRequests:
            try:
                decodedRequest = self._decodeRequest(encodedRequest)
            except InvalidRequest:
                continue
            yield decodedRequest

    def _validateFifosExist(self):
        logger.info("Validating fifos exist.")
        fifos = (self._reclamationRequestFifoPath, self._softReclamationFailedMsgFifoPath)
        for fifo in fifos:
            if not os.path.exists(fifo):
                os.mkfifo(fifo)

    def _openFifos(self):
        self._openRequestsFifo()
        self._openSoftReclaimFailureMessageFifo()

    def _openRequestsFifo(self):
        logger.info("Opening request fifo for reading...")
        self._requestsReadFd = os.open(self._reclamationRequestFifoPath, os.O_RDONLY)
        logger.info("Fifo open.")

    def _openSoftReclaimFailureMessageFifo(self):
        logger.info("Opening soft-reclaim-failure message fifo for reading...")
        self._softReclamationFailedMsgFifoWriteFd = os.open(self._softReclamationFailedMsgFifoPath,
                                                            os.O_WRONLY)
        logger.info("Fifo open.")

    def _handleEmptyStringFromPipe(self):
        os.close(self._requestsReadFd)
        logger.info("Reopening requests queue...")
        self._openRequestsFifo()

    def _readRequestsFromPipe(self):
        encoded = ""
        while not encoded:
            encoded = os.read(self._requestsReadFd, self._BUF_SIZE)
            if not encoded:
                self._handleEmptyStringFromPipe()
                continue
            encoded = encoded.strip(" ,")
            decoded = self._decodeRequests(encoded)
        for actionType, args in decoded:
            yield actionType, args

    def _cleanup(self):
        os.close(self._softReclamationFailedMsgFifoWriteFd)
        os.close(self._requestsReadFd)

    def _executeRequest(self, actionType, args):
        action = self._actionTypes[actionType]
        logger.info("Executing command %(command)s with args %(args)s",
                     dict(command=actionType, args=args))
        try:
            callback = action(*args)
            if isinstance(callback, threading.Thread):
                self._monitor.add(callback)
        except Exception as e:
            logger.error("An error has occurred while executing request: %(message)s",
                          dict(message=e.message))
