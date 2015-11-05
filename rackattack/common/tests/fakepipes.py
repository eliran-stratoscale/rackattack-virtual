import os
import select
from rackattack.common.tests.fakeepoll import FakeEpoll


class FakePipe:
    FAKE_FIFO_FD_COUNTER = 2000

    def __init__(self):
        self.content = ""
        self.readFd = None
        self.writeFd = None

    def read(self, length):
        assert self.readFd is not None
        length = min(length, len(self.content))
        readContent = self.content[:length]
        self.content = self.content[length:]
        return readContent

    def write(self, content):
        assert self.writeFd is not None
        self.content += content
        return len(content)

    def open(self, *args, **kwargs):
        fd = None
        if os.O_RDONLY == args[0]:
            assert self.readFd is None
            self.readFd = self._generateFd()
            fd = self.readFd
        elif os.O_WRONLY == args[0]:
            assert self.writeFd is None
            self.writeFd = self._generateFd()
            fd = self.writeFd
        assert fd is not None
        return fd

    def _generateFd(self):
        FakePipe.FAKE_FIFO_FD_COUNTER += 1
        return FakePipe.FAKE_FIFO_FD_COUNTER


class FakeNamedPipe(FakePipe):
    def __init__(self, filename):
        FakePipe.__init__(self)
        self.filename = filename
        self.content = ""


class FakePipeMethods:
    origOsOpen = os.open
    origOsWrite = os.write
    origOsRead = os.read
    origOsMkfifo = os.mkfifo
    origOsPipe = os.pipe
    origSelectEpoll = select.epoll

    def __init__(self, modulesInWhichToSetupMocks, fakeFilesystem):
        self.fakePipes = list()
        self._fakeFilesystem = fakeFilesystem
        self._enable(modulesInWhichToSetupMocks)

    @classmethod
    def disable(cls, modulesInWhichToRestoreMethods):
        for module in modulesInWhichToRestoreMethods:
            if hasattr(module, 'os'):
                module.os.open = cls.origOsOpen
                module.os.write = cls.origOsWrite
                module.os.read = cls.origOsRead
                module.os.mkfifo = cls.origOsMkfifo
                module.os.pipe = cls.origOsPipe
            if hasattr(module, 'select'):
                module.select.epoll = cls.origSelectEpoll

    def _enable(self, modulesInWhichToSetupMocks):
        for module in modulesInWhichToSetupMocks:
            if hasattr(module, 'os'):
                module.os.open = self.osOpen
                module.os.write = self.osWrite
                module.os.read = self.osRead
                module.os.mkfifo = self.osMkfifo
                module.os.pipe = self.osPipe
            if hasattr(module, 'select'):
                module.select.epoll = self.selectEpoll

    def osWrite(self, fd, content):
        fifo = self.getPipeByWriteFd(fd)
        if isinstance(fifo, FakeNamedPipe):
            assert self._fakeFilesystem.Exists(fifo.filename)
        return fifo.write(content)

    def osRead(self, fd, length):
        fifo = self.getPipeByReadFd(fd)
        if isinstance(fifo, FakeNamedPipe):
            assert self._fakeFilesystem.Exists(fifo.filename)
        return fifo.read(length)

    def osMkfifo(self, filename, *args, **kwargs):
        assert not self._fakeFilesystem.Exists(filename), filename
        self._validateFifoDoesNotExist(filename)
        self._fakeFilesystem.CreateFile(filename, create_missing_dirs=True)
        fakeFifo = FakeNamedPipe(filename)
        self.fakePipes.append(fakeFifo)

    def osPipe(self, *args, **kwargs):
        fakePipe = FakePipe()
        self.fakePipes.append(fakePipe)
        readFd = fakePipe.open(os.O_RDONLY)
        writeFd = fakePipe.open(os.O_WRONLY)
        return readFd, writeFd

    def selectEpoll(self):
        fakeEpollPoller = FakeEpoll(self.fakePipes)
        return fakeEpollPoller

    def osOpen(self, filename, *args, **kwargs):
        assert self._fakeFilesystem.Exists(filename)
        fifo = self.getFifoByFilename(filename)
        fd = fifo.open(*args, **kwargs)
        return fd

    def getFifoContent(self, filename):
        assert self._fakeFilesystem.Exists(filename)
        fifo = self.getFifoByFilename(filename)
        return fifo.content

    def _getFifoFilenames(self):
        return [fakePipe.filename for fakePipe in self.fakePipes if isinstance(fakePipe, FakeNamedPipe)]

    def _validateFifoExists(self, filename):
        fifoFilenames = self._getFifoFilenames()
        assert filename in fifoFilenames

    def _validateFifoDoesNotExist(self, filename):
        fifoFilenames = self._getFifoFilenames()
        assert filename not in fifoFilenames

    def getPipeByWriteFd(self, fd):
        for pipe in self.fakePipes:
            if pipe.writeFd == fd:
                return pipe
            assert pipe.readFd != fd
        assert False

    def getPipeByReadFd(self, fd):
        for pipe in self.fakePipes:
            if pipe.readFd == fd:
                return pipe
            assert pipe.writeFd != fd
        assert False

    def getFifoByFilename(self, filename):
        fifos = [pipe for pipe in self.fakePipes if isinstance(pipe, FakeNamedPipe)]
        matchingFifos = [fifo for fifo in fifos if fifo.filename == filename]
        assert matchingFifos
        return matchingFifos[0]
