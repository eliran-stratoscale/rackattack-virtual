import os
import base64
import logging
import threading
import functools
from rackattack.common import tftpboot, softreclaim


logger = logging.getLogger("reclamation")


def getContents(_path):
    with open(_path, "rb") as _file:
        contents = _file.read()
    return contents


class ThreadsMonitor:
    def __init__(self):
        self._threads = set()

    def add(self, _thread):
        self._threads.add(_thread)
        del _thread
        self._threads = set([_thread for _thread in self._threads if _thread.isAlive()])
        nrThreads = len(self._threads)
        logger.info("Currently running %(nrThreads)s threads.", dict(nrThreads=nrThreads))


class InauguratorCommandLine:
    def __init__(self, netmask, osmosisServerIP, inauguratorServerIP, inauguratorServerPort,
                 inauguratorGatewayIP, rootPassword, withLocalObjectStore):
        self._netmask = netmask
        self._osmosisServerIP = osmosisServerIP
        self._inauguratorServerIP = inauguratorServerIP
        self._inauguratorServerPort = inauguratorServerPort
        self._inauguratorGatewayIP = inauguratorGatewayIP
        self._rootPassword = rootPassword
        self._withLocalObjectStore = withLocalObjectStore

    def __call__(self, id, mac, ip, clearDisk):
        result = tftpboot._INAUGURATOR_COMMAND_LINE % dict(
            macAddress=mac, ipAddress=ip, netmask=self._netmask,
            osmosisServerIP=self._osmosisServerIP, inauguratorServerIP=self._inauguratorServerIP,
            inauguratorServerPort=self._inauguratorServerPort,
            inauguratorGatewayIP=self._inauguratorGatewayIP,
            rootPassword=self._rootPassword,
            id=id)
        if self._withLocalObjectStore:
            result += " --inauguratorWithLocalObjectStore"
        if clearDisk:
            result += " --inauguratorClearDisk"
        return result


class InvalidRequest(Exception):
    pass


class ReclamationServer:
    # A large buffer size is needed to avoid the need for reassembly of chunks read from the pipe.
    _BUF_SIZE = 1024 ** 2

    def __init__(self,
                 netmask,
                 osmosisServerIP,
                 inauguratorServerIP,
                 inauguratorServerPort,
                 inauguratorGatewayIP,
                 rootPassword,
                 withLocalObjectStore,
                 reclamationRequestFifoPath,
                 softReclamationFailedMsgFifoPath):
        self._inauguratorCommandLine = InauguratorCommandLine(netmask,
                                                              osmosisServerIP,
                                                              inauguratorServerIP,
                                                              inauguratorServerPort,
                                                              inauguratorGatewayIP,
                                                              rootPassword,
                                                              withLocalObjectStore)
        self._reclamationRequestFifoPath = reclamationRequestFifoPath
        self._softReclamationFailedMsgFifoPath = softReclamationFailedMsgFifoPath
        self._monitor = ThreadsMonitor()
        self._requestsReadFd = None
        self._softReclamationFailedMsgFifoWriteFd = None
        self._inauguratorKernel = None
        self._inauguratorInitRD = None
        self._actionTypes = dict()

    def _setup(self):
        self._validateFifosExist()
        self._openFifos()
        self._inauguratorKernel = getContents(tftpboot.INAUGURATOR_KERNEL)
        self._inauguratorInitRD = getContents(tftpboot.INAUGURATOR_INITRD)
        self._actionTypes["soft"] = functools.partial(
            softreclaim.SoftReclaim,
            inauguratorCommandLine=self._inauguratorCommandLine,
            softReclamationFailedMsgFifoWriteFd=self._softReclamationFailedMsgFifoWriteFd,
            inauguratorKernel=self._inauguratorKernel,
            inauguratorInitRD=self._inauguratorInitRD)

    def registerAction(self, _type, callback):
        assert _type not in self._actionTypes
        self._actionTypes[_type] = callback

    def run(self):
        self._setup()
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