import select


class FakeEpoll:
    def __init__(self, fakePipesMock):
        self._registeredEvents = set()
        self.fakePipesMock = fakePipesMock

    def register(self, fd, eventmask):
        """Only supporsts polling for read ends right now"""
        self._registeredEvents.add((fd, eventmask))

    def poll(self):
        events = []
        for fd, _ in list(self._registeredEvents):
            pipe = self.fakePipesMock.getPipeByReadFd(fd)
            if pipe.content:
                events.append((pipe.readFd, select.EPOLLIN))
        return events
