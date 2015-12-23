import threading
import inaugurator.server.config
from rackattack.virtual.kvm import config
from rackattack.virtual.kvm import network
from rackattack.common import reclamationserver, reclaimhostspooler


class VirtualReclamationServer(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self._reclamationserver = \
            reclamationserver.ReclamationServer(network.NETMASK,
                                                network.GATEWAY_IP_ADDRESS,
                                                network.GATEWAY_IP_ADDRESS,
                                                inaugurator.server.config.PORT,
                                                network.GATEWAY_IP_ADDRESS,
                                                config.ROOT_PASSWORD,
                                                False,
                                                config.RECLAMATION_REQUESTS_FIFO_PATH,
                                                config.SOFT_RECLAMATION_FAILURE_MSG_FIFO_PATH)
        threading.Thread.start(self)

    def run(self):
        self._reclamationserver.run()


class ReclaimHost(reclaimhostspooler.ReclaimHostSpooler):
    def __init__(self, *args, **kwargs):
        reclaimhostspooler.ReclaimHostSpooler.__init__(self, *args, **kwargs)

    def _handleColdReclamationRequest(self, host, hardReset):
        del hardReset
        host.coldRestart()
