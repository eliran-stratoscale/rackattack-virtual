import os
import threading
import logging
import Queue
import base64
import select
from rackattack.tcp import suicide
from rackattack.common import globallock


class ReclaimHostSpooler(threading.Thread):
    _READ_BUF_SIZE = 1024 ** 2

    def __init__(self, hosts, requestFifoPath, softReclaimFailedMsgFifoPath):
        threading.Thread.__init__(self)
        self.daemon = True
        self._hosts = hosts
        self._reclamationRequestFd = requestFifoPath
        self._softReclaimFailedMsgFifoPath = softReclaimFailedMsgFifoPath
        self._serverRequestFd = None
        self._softReclaimFailedFd = None
        self._queue = Queue.Queue()
        self._reclamationHandlers = dict(soft=self._handleSoftReclamationRequest,
                                         cold=self._handleColdReclamationRequest)
        self.start()

    def run(self):
        self._setupFifos()
        poller = self._generatePoller()
        actions = {self._softReclaimFailedFd: self._handleSoftReclamationFailedMsg,
                   self._notifyThreadReadFd: self._handleReclamationRequest}
        logging.info("Reclaim-host request spooler thread is ready.")
        while True:
            events = poller.poll()
            for fd, _ in events:
                action = actions[fd]
                try:
                    action()
                except Exception as e:
                    logging.error("Error in reclamation-spooler thread: %(message)s. Commiting suicide.",
                                  dict(message=e.message))
                    suicide.killSelf()
                    raise

    def cold(self, host, reconfigureBIOS=False):
        del reconfigureBIOS
        self._notifyReclamationRequest(host, requestType="cold")

    def soft(self, host):
        self._notifyReclamationRequest(host, requestType="soft")

    @classmethod
    def _validateFifoExists(self, path):
        if not os.path.exists(path):
            os.mkfifo(path)

    def _setupFifos(self):
        self._validateFifoExists(self._reclamationRequestFd)
        logging.info("Waiting for Reclamation request fifo to be open for writing...")
        assert self._serverRequestFd is None
        self._serverRequestFd = os.open(self._reclamationRequestFd, os.O_WRONLY)
        self._validateFifoExists(self._softReclaimFailedMsgFifoPath)
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

    def _notifyReclamationRequest(self, host, requestType):
        cmd = dict(_type=requestType, kwargs=dict(host=host))
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

    def _handleSoftReclamationRequest(self, host):
        credentials = host.rootSSHCredentials()
        args = [host.id(),
                credentials["hostname"],
                credentials["username"],
                credentials["password"],
                host.primaryMACAddress()]
        self._sendRequest("soft", args)

    def _sendRequest(self, _type, args):
        args = [_type] + args
        encodedRequest = base64.encodestring(",".join(args))
        encodedRequest += ","
        os.write(self._serverRequestFd, encodedRequest)

    def _handleColdReclamationRequest(self, host):
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
