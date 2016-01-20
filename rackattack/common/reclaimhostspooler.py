import os
import threading
import logging
import Queue
import base64
import select
from rackattack.tcp import suicide
from rackattack.common import globallock, createfifos


class ReclaimHostSpooler(threading.Thread):
    _READ_BUF_SIZE = 1024 ** 2

    def __init__(self, hosts, requestFifoPath, softReclaimFailedMsgFifoPath):
        threading.Thread.__init__(self)
        self.daemon = True
        self._hosts = hosts
        self._reclamationRequestFifoPath = requestFifoPath
        self._softReclaimFailedMsgFifoPath = softReclaimFailedMsgFifoPath
        self._reclamationRequestFd = None
        self._softReclaimFailedFd = None
        self._queue = Queue.Queue()
        self._reclamationHandlers = dict(soft=self._handleSoftReclamationRequest,
                                         cold=self._handleColdReclamationRequest)
        self._notifyThreadReadFd = None
        self._notifyThreadWriteFd = None
        self._isReady = threading.Event()
        self.start()
        logging.info("Reclaim-Host-Spooler is waiting for fifos to be set up...")
        self._isReady.wait()
        logging.info("Reclaim-Host-Spooler is ready.")

    def run(self):
        self._setupFifos()
        poller = self._generatePoller()
        actions = {self._softReclaimFailedFd: self._handleSoftReclamationFailedMsg,
                   self._notifyThreadReadFd: self._handleReclamationRequest}
        self._isReady.set()
        while True:
            events = poller.poll()
            for fd, _ in events:
                action = actions[fd]
                try:
                    action()
                except Exception as e:
                    logging.exception("Error in reclamation-spooler: %(message)s. Commiting suicide.",
                                      dict(message=e.message))
                    suicide.killSelf()
                    raise

    def cold(self, host, reconfigureBIOS=False, hardReset=False):
        del reconfigureBIOS
        self._notifyReclamationRequest(host, requestType="cold", hardReset=hardReset)

    def soft(self, host, isInauguratorActive=False):
        self._notifyReclamationRequest(host, requestType="soft", isInauguratorActive=isInauguratorActive)

    def _setupFifos(self):
        createfifos.validateFifoExists(self._reclamationRequestFifoPath)
        logging.info("Waiting for Reclamation request fifo to be open for writing...")
        assert self._reclamationRequestFd is None
        self._reclamationRequestFd = os.open(self._reclamationRequestFifoPath, os.O_WRONLY)
        createfifos.validateFifoExists(self._softReclaimFailedMsgFifoPath)
        logging.info("Waiting for soft-reclaim-failed message pipe to open for writing...")
        assert self._softReclaimFailedFd is None
        self._softReclaimFailedFd = os.open(self._softReclaimFailedMsgFifoPath, os.O_RDONLY)
        logging.info("Fifos open.")
        self._notifyThreadReadFd, self._notifyThreadWriteFd = os.pipe()

    def _generatePoller(self):
        poller = select.epoll()
        poller.register(self._softReclaimFailedFd, eventmask=select.EPOLLIN)
        poller.register(self._notifyThreadReadFd, eventmask=select.EPOLLIN)
        return poller

    def _notifyReclamationRequest(self, host, requestType, **kwargs):
        requestArgs = dict(kwargs)
        requestArgs["host"] = host
        cmd = dict(_type=requestType, kwargs=requestArgs)
        self._queue.put(cmd)
        os.write(self._notifyThreadWriteFd, "1")

    def _handleReclamationRequest(self):
        notificationBytes = os.read(self._notifyThreadReadFd, self._READ_BUF_SIZE)
        nrCommands = len(notificationBytes)
        for _ in xrange(nrCommands):
            cmd = self._queue.get(block=True)
            cmdType = cmd["_type"]
            kwargs = cmd["kwargs"]
            action = self._reclamationHandlers[cmdType]
            action(**kwargs)

    def _handleSoftReclamationRequest(self, host, isInauguratorActive):
        credentials = host.rootSSHCredentials()
        targetDevice = host.targetDevice()
        if targetDevice is None:
            targetDevice = "default"
        args = [host.id(),
                credentials["hostname"],
                credentials["username"],
                credentials["password"],
                host.primaryMACAddress(),
                targetDevice,
                str(isInauguratorActive)]
        self._sendRequest("soft", args)

    def _sendRequest(self, _type, args):
        args = [_type] + args
        encodedRequest = base64.encodestring(",".join(args))
        encodedRequest += ","
        os.write(self._reclamationRequestFd, encodedRequest)

    def _handleColdReclamationRequest(self, host, hardReset):
        raise NotImplementedError

    def _handleSoftReclamationFailedMsg(self):
        hostsIDs = os.read(self._softReclaimFailedFd, self._READ_BUF_SIZE)
        hostsIDs = hostsIDs.split(",")
        for hostID in hostsIDs:
            if not hostID:
                continue
            with globallock.lock():
                try:
                    host = self._hosts.byID(hostID)
                except:
                    logging.warn("A soft reclamation failure  notification was received for a non-existent "
                                 "host %(hostID)s", dict(hostID=hostID))
                    continue
                try:
                    host.softReclaimFailed()
                except Exception as e:
                    logging.error("Error handling soft reclamation failure for host %(host)s: %(message)s",
                                  dict(host=hostID, message=e.message))
