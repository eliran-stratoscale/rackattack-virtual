import threading
import logging
import simplejson
from rackattack.tcp import suicide
from rackattack.tcp import debug
from rackattack import api
from rackattack.common import globallock
from rackattack.common import dynamicconfig
import Queue


class BaseIPCServer(threading.Thread):
    def __init__(self):
        self._queue = Queue.Queue()
        threading.Thread.__init__(self)
        self.daemon = True
        threading.Thread.start(self)

    def cmd_handshake(self, versionInfo, peer):
        if versionInfo['RACKATTACK_VERSION'] != api.VERSION:
            raise Exception(
                "Rackattack API version on the client side is '%s', and '%s' on the provider" % (
                    versionInfo['RACKATTACK_VERSION'], api.VERSION))

    def cmd_admin__reloadStateMachineConfiguration(self, peer):
        dynamicconfig.reloadConfiguration()

    def cmd_admin__printStateMachineConfiguration(self, peer):
        dynamicconfig.printConfiguration()

    def run(self):
        try:
            while True:
                try:
                    self._work()
                except:
                    logging.exception("Handling")
        except:
            logging.exception("IPC server aborts")
            suicide.killSelf()
            raise

    def handle(self, string, respondCallback, peer):
        try:
            incoming = simplejson.loads(string)
            if incoming['cmd'] == 'handshake':
                with debug.logNetwork("Handling handshake"):
                    response = self.cmd_handshake(peer=peer, ** incoming['arguments'])
                    respondCallback(simplejson.dumps(response))
            else:
                transaction = debug.Transaction("Handling: %s" % incoming['cmd'])
                self._queue.put((incoming, peer, respondCallback, transaction))
        except Exception, e:
            logging.exception('Handling')
            response = dict(exceptionString=str(e), exceptionType=e.__class__.__name__)
            respondCallback(simplejson.dumps(response))

    def _work(self):
        incoming, peer, respondCallback, transaction = self._queue.get()
        transaction.reportState('dequeued (%d left in queue)' % self._queue.qsize())
        try:
            handler = getattr(self, "cmd_" + incoming['cmd'])
            with globallock.lock():
                response = handler(peer=peer, ** incoming['arguments'])
        except Exception, e:
            logging.exception('Handling')
            response = dict(exceptionString=str(e), exceptionType=e.__class__.__name__)
        transaction.finished()
        respondCallback(simplejson.dumps(response))
