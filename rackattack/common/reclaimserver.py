import os
import time
import base64
import select
import logging
import asyncio
import argparse
import asyncssh
import functools
from rackattack.common import tftpboot


logger = logging.getLogger("reclamation")


class KexecDoesNotExistOnHost(Exception):
    pass


class MySSHClientSession(asyncssh.SSHClientSession):
    def __init__(self):
        self.data = None

    def data_received(self, data, datatype):
        self.data = data

    def connection_lost(self, exc):
        if exc:
            print('SSH session error: ' + str(exc), file=sys.stderr)

class MySSHClient(asyncssh.SSHClient):
    def connection_made(self, conn):
        print('Connection made to %s.' % conn.get_extra_info('peername')[0])

    def auth_completed(self):
        print('Authentication successful.')


class SoftReclaim:
    _AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN = 60 * 60 * 24
    _KEXEC_CMD = "kexec"

    def __init__(self,
                 inauguratorCommandLine,
                 softReclamationFailedMsgFifoWriteFd,
                 hostID,
                 hostname,
                 username,
                 password,
                 macAddress):
        self._inauguratorCommandLine = inauguratorCommandLine
        self._softReclamationFailedMsgFifoWriteFd = softReclamationFailedMsgFifoWriteFd
        self._hostID = hostID
        self._hostname = hostname
        self._username = username
        self._password = password
        self._macAddress = macAddress
        self._sftp = None
        #self._connection = connection.Connection(hostname=self._hostname,
        #                                         username=self._username,
        #                                         password=self._password)

    @asyncio.coroutine
    def _getUptime(self, sftp):
        uptimeFile = yield from sftp.open("/proc/uptime")
        uptime = yield from uptimeFile.read()
        # No need to close the file since the machine is about to reboot
        uptime = uptime.strip()
        uptime = uptime.split(" ")[0]
        uptime = float(uptime)
        return uptime

    @asyncio.coroutine
    def _validateUptime(self, sftp):
        uptime = yield from self._getUptime(sftp)
        print("Uptime: %s" % (str(uptime),))
        if uptime > self._AVOID_RECLAIM_BY_KEXEC_IF_UPTIME_MORE_THAN:
            print("Uptime too long for %(hostID)s: %(uptime)s" % dict(hostID=self._hostID, uptime=uptime))
            raise ValueError(uptime)

    @asyncio.coroutine
    def run(self):
        print("Attempting to connect...")
        conn, client = yield from asyncssh.create_connection(MySSHClient, '10.0.0.101',
                                                            username="root",
                                                            password="strato")
        with conn:
            sftp = yield from conn.start_sftp_client()
            yield from self._validateUptime(sftp)
            yield from sftp.put(tftpboot.INAUGURATOR_KERNEL, remotepath="/tmp/vmlinuz")
            print("Done transfering vmlinuz")
            yield from sftp.put(tftpboot.INAUGURATOR_INITRD, remotepath="/tmp/initrd")
            print("Done transfering initrd")
            kexecConfigCMD = "%s --load /tmp/vmlinuz --initrd=/tmp/initrd --append='%s'" % \
                (self._KEXEC_CMD,
                 self._inauguratorCommandLine(self._hostID, self._macAddress, self._hostname,
                                              clearDisk=False))
            chan, session = yield from conn.create_session(MySSHClientSession, kexecConfigCMD)
            print("Done configuring kexec")
            kexecCMD = "sleep 2; %s -e" % (self._KEXEC_CMD,)
            chan, session = yield from conn.create_session(MySSHClientSession, kexecCMD)
            print("Done running kexec")

    def _sendSoftReclaimFailedMsg(self):
        msg = "%(hostID)s," % (dict(hostID=self._hostID))
        logger.info("Sending Soft-reclamation-failed message for '%(id)s'...", dict(id=self._hostID))
        os.write(self._softReclamationFailedMsgFifoWriteFd, msg)
        logger.info("Message sent for '%(id)s'.", dict(id=self._hostID))


class InvalidRequest(Exception):
    pass


class IOLoop:
    # A large buffer size is needed to avoid the need for reassembly of chunks read from the pipe.
    _BUF_SIZE = 1024 ** 2

    def __init__(self, inauguratorCommandLine, reclamationRequestFifoPath, softReclamationFailedMsgFifoPath):
        self._inauguratorCommandLine = inauguratorCommandLine
        self._reclamationRequestFifoPath = reclamationRequestFifoPath
        self._softReclamationFailedMsgFifoPath = softReclamationFailedMsgFifoPath
        self._softReclamationFailedMsgFifoWriteFd = None
        self._fifos = dict(requests=dict(path=reclamationRequestFifoPath, fd=None),
                           softReclamationFailedMsg=dict(path=softReclamationFailedMsgFifoPath, fd=None))
        self._openForReading("requests")
        self._openForWriting("softReclamationFailedMsg")
        self._actionTypes = dict(soft=functools.partial(self._softReclaim, inauguratorCommandLine, self._fifos["softReclamationFailedMsg"]["fd"]))
        self._loop = asyncio.get_event_loop()

    def registerAction(self, _type, callback):
        assert _type not in self._actionTypes
        self._actionTypes[_type] = callback

    def run(self):
        self._loop.add_reader(self._fifos["requests"]["fd"], functools.partial(self._reader, "requests", self._processDataFromRequestsPipe))
        self._loop.run_forever()
        self._cleanup()

    def _reader(self, fifoName, processDataCoroutine):
        fd = self._fifos[fifoName]["fd"]
        data = os.read(fd, self._BUF_SIZE)
        if data:
            print("Received from pipe:", data.decode())
            self._loop.create_task(processDataCoroutine(data))
        else:
            self._handleFifoEOF(fifoName)

    def _handleFifoEOF(self, fifoName, processDataCoroutine):
        fd = self._fifos[fifoName]["fd"]
        self._loop.remove_reader(fd)
        os.close(fd)
        self._openForReading(fifoName)
        loop.add_reader(fd, functools.partial(reader, fifoName, self._processDataFromRequestePipe))

    @asyncio.coroutine
    def _processDataFromRequestsPipe(self, data):
        encodedRequests = data.strip(" ,".encode("utf-8"))
        requests = self._decodeRequests(encodedRequests)
        if requests is not None:
            for actionType, args in requests:
                self._executeRequest(actionType, args)

    @asyncio.coroutine
    def _softReclaim(self, inauguratorCommandLine, softReclamationFailedMsgFifoWriteFd, *args, **kwargs):
        softReclaim = SoftReclaim(_inauguratorCommandLine,
                                  softReclamationFailedMsgFifoWriteFd,
                                  *args,
                                  **kwargs)
        yield from softReclaim.run()

    def _decodeRequest(self, request):
        try:
            request = base64.decodestring(request)
            if not request:
                raise ValueError(request)
        except:
            logger.error("Could not decode request's base64: %(request)s", dict(request=request))
            raise InvalidRequest(request)
        request = request.decode("utf-8")
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
        encodedRequests = encodedRequests.split(",".encode("utf-8"))
        for encodedRequest in encodedRequests:
            try:
                decodedRequest = self._decodeRequest(encodedRequest)
            except InvalidRequest:
                continue
            yield decodedRequest

    def _validateFifoExists(self, _path):
        logger.info("Validating fifo %(_path)s exist.", dict(_path=_path))
        if not os.path.exists(_path):
            os.mkfifo(_path, mode=0o777)

    def _openForReading(self, fifoName):
        fifo = self._fifos[fifoName]
        _path = fifo["path"]
        self._validateFifoExists(_path)
        logger.info("Opening %(_path)s for reading...", dict(_path=_path))
        fifo["fd"] = os.open(fifo["path"], os.O_RDONLY | os.O_NONBLOCK)
        logger.info("Fifo open.")

    def _openForWriting(self, fifoName):
        fifo = self._fifos[fifoName]
        _path = fifo["path"]
        self._validateFifoExists(_path)
        logger.info("Opening %(_path)s for writing...", dict(_path=_path))
        fifo["fd"] = os.open(fifo["path"], os.O_WRONLY)
        logger.info("Fifo open.")

    def _cleanup(self):
        os.close(self._softReclamationFailedMsgFifoWriteFd)
        os.close(self._requestsReadFd)

    def _executeRequest(self, actionType, args):
        action = self._actionTypes[actionType]
        logger.info("Executing command %(command)s with args %(args)s",
                     dict(command=actionType, args=args))
        try:
            self._loop.create_task(action(*args))
        except Exception as e:
            logger.error("An error has occurred while executing request: %(message)s",
                          dict(message=str(e)))
