from rackattack.common import globallock
from rackattack.tcp import debug
from inaugurator.server import server
from inaugurator.server import rabbitmqwrapper
import logging


class Inaugurate:
    def __init__(self, filesPath):
        self._registered = {}
        self._rabbit = rabbitmqwrapper.RabbitMQWrapper(filesPath)
        self._server = server.Server(
            checkInCallback=self._checkIn, doneCallback=self._done, progressCallback=self._progress)

    def register(self, id, checkInCallback, doneCallback, progressCallback):
        assert globallock.assertLocked()
        assert id not in self._registered
        self._server.listenOnID(id)
        self._registered[id] = dict(
            checkInCallback=checkInCallback, doneCallback=doneCallback,
            progressCallback=progressCallback)

    def unregister(self, id):
        assert globallock.assertLocked()
        assert id in self._registered
        del self._registered[id]
        #self._server.stopListeningOnID(id)

    def provideLabel(self, id, label):
        logging.info("%(id)s received label '%(label)s'", dict(id=id, label=label))
        with debug.logNetwork("Providing label '%(label)s' to '%(id)s'" % dict(label=label, id=id)):
            self._server.provideLabel(id=id, label=label)

    def _checkIn(self, id):
        logging.info("%(id)s inaugurator check in", dict(id=id))
        with globallock.lock():
            if id not in self._registered:
                logging.error("Unknown Inaugurator checked in: %(id)s", dict(id=id))
                return
            self._registered[id]['checkInCallback']()

    def _done(self, id):
        logging.info("%(id)s done", dict(id=id))
        with globallock.lock():
            if id not in self._registered:
                logging.error("Unknown Inaugurator done: %(id)s", dict(id=id))
                return
            self._registered[id]['doneCallback']()

    def _progress(self, id, progress):
        if u'state' in progress and progress[u'state'] == 'digesting':
            return
        with globallock.lock():
            if id not in self._registered:
                logging.error("Unknown Inaugurator progress: %(id)s", dict(id=id))
                return
            self._registered[id]['progressCallback'](progress)
