import os
import threading
import logging
import time
import Queue
import base64
import select
from rackattack.tcp import suicide
from rackattack.ssh import connection
from rackattack.common import tftpboot
from rackattack.common import globallock


class ReclaimHostSpooler(threading.Thread):
    READ_BUF_SIZE = 1024 ** 2

    def __init__(self, hosts, requestFifoPath, softReclaimFailedFifoPath):
        threading.Thread.__init__(self)
        self.daemon = True
        self._hosts = hosts
        if not os.path.exists(requestFifoPath):
            os.mkfifo(requestFifoPath)
        if not os.path.exists(softReclaimFailedFifoPath):
            os.mkfifo(softReclaimFailedFifoPath)
        self._queue = Queue.Queue()
        logging.info("Waiting for Reclamation request fifo to be open for writing...")
        self._serverRequestFd = os.open(requestFifoPath, os.O_WRONLY)
        logging.info("Waiting for soft-reclaim-failed message pipe to open for writing...")
        self._softReclaimFailedFd = os.open(softReclaimFailedFifoPath, os.O_RDONLY)
        self._notifyThreadReadFd, self._notifyThreadWriteFd = os.pipe()
        self._poller = select.epoll()
        self._poller.register(self._softReclaimFailedFd, eventmask=select.EPOLLIN)
        self._poller.register(self._notifyThreadReadFd, eventmask=select.EPOLLIN)
        self.start()
        logging.info("Reclaim-host request spooler thread is ready.")

    def run(self):
        actions = {self._softReclaimFailedFd: self._handleSoftReclamationFailed,
                   self._notifyThreadReadFd: self._handleReclamationRequestNotification}
        while True:
            events = self._poller.poll()
            for fd, _ in events:
                action = actions[fd]
                try:
                    action()
                except Exception as e:
                    logging.error("Error in reclamation-spooler thread: %(message)s. Commiting suicide.",
                                  dict(message=e.message))
                    suicide.killSelf()
                    raise

    def _notifyReclamationRequest(self, host, requestType):
        cmd = dict(_type=requestType, kwargs=dict(host=host))
        self._queue.put(cmd)
        os.write(self._notifyThreadWriteFd, "1")

    def cold(self, host, reconfigureBIOS=False):
        del reconfigureBIOS
        self._notifyReclamationRequest(host, requestType="cold")

    def soft(self, host):
        self._notifyReclamationRequest(host, requestType="soft")

    def _handleReclamationRequestNotification(self):
        actions = dict(soft=self._handleSoftReclamationRequest,
                       cold=self._handleColdReclamationRequest)
        notificationBytes = os.read(self._notifyThreadReadFd, self.READ_BUF_SIZE)
        nrCommands = len(notificationBytes)
        for _ in xrange(nrCommands):
            cmd = self._queue.get(block=True)
            cmdType = cmd["_type"]
            kwargs = cmd["kwargs"]
            action = actions[cmdType]
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

    def _handleSoftReclamationFailed(self):
        hostsIDs = os.read(self._softReclaimFailedFd, self.READ_BUF_SIZE)
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
