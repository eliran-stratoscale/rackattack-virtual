import logging
import argparse
from rackattack.virtual import logconfig
from rackattack.virtual import ipcserver
from rackattack.virtual import buildimagethread
from rackattack.virtual.kvm import cleanup
import rackattack.virtual.handlekill
from rackattack.virtual.kvm import config
from rackattack.virtual.kvm import network
from rackattack.virtual.kvm import vm
from rackattack.virtual.kvm import imagestore
from rackattack.common import dnsmasq
from rackattack.common import globallock
from rackattack.common import tftpboot
from rackattack.common import inaugurate
from rackattack.common import timer
from rackattack.virtual.alloc import allocations
from rackattack.tcp import publish
from rackattack.tcp import transportserver
from twisted.internet import reactor
from twisted.web import server
from rackattack.common import httprootresource
import inaugurator.server.config
import atexit
from rackattack.virtual import reclaimhost

parser = argparse.ArgumentParser()
parser.add_argument("--requestPort", default=1014, type=int)
parser.add_argument("--subscribePort", default=1015, type=int)
parser.add_argument("--httpPort", default=1016, type=int)
parser.add_argument("--maximumVMs", type=int)
parser.add_argument("--diskImagesDirectory")
parser.add_argument("--serialLogsDirectory")
parser.add_argument("--managedPostMortemPacksDirectory")
parser.add_argument("--rabbitMQDirectory")
args = parser.parse_args()

if args.maximumVMs:
    config.MAXIMUM_VMS = args.maximumVMs
if args.diskImagesDirectory:
    config.DISK_IMAGES_DIRECTORY = args.diskImagesDirectory
if args.serialLogsDirectory:
    config.SERIAL_LOGS_DIRECTORY = args.serialLogsDirectory
if args.managedPostMortemPacksDirectory:
    config.MANAGED_POST_MORTEM_PACKS_DIRECTORY = args.managedPostMortemPacksDirectory
if args.rabbitMQDirectory:
    config.RABBIT_MQ_DIRECTORY = args.rabbitMQDirectory

cleanup.cleanup()
atexit.register(cleanup.cleanup)
timer.TimersThread()
network.setUp()
tftpbootInstance = tftpboot.TFTPBoot(
    netmask=network.NETMASK,
    inauguratorServerIP=network.GATEWAY_IP_ADDRESS,
    inauguratorServerPort=inaugurator.server.config.PORT,
    inauguratorGatewayIP=network.GATEWAY_IP_ADDRESS,
    osmosisServerIP=network.GATEWAY_IP_ADDRESS,
    rootPassword=config.ROOT_PASSWORD,
    withLocalObjectStore=False)
dnsmasq.DNSMasq.killSpecificPrevious(serverIP=network.GATEWAY_IP_ADDRESS)
dnsmasqInstance = dnsmasq.DNSMasq(
    tftpboot=tftpbootInstance,
    serverIP=network.GATEWAY_IP_ADDRESS,
    netmask=network.NETMASK,
    firstIP=network.FIRST_IP,
    lastIP=network.LAST_IP,
    gateway=network.GATEWAY_IP_ADDRESS,
    nameserver=network.GATEWAY_IP_ADDRESS,
    interface="rackattacknetbr")
reclamationServer = reclaimhost.VirtualReclamationServer()
reclaimHost = reclaimhost.ReclaimHost(None,
                                      config.RECLAMATION_REQUESTS_FIFO_PATH,
                                      config.SOFT_RECLAMATION_FAILURE_MSG_FIFO_PATH)
for mac, ip in network.allNodesMACIPPairs():
    dnsmasqInstance.add(mac, ip)
inaugurateInstance = inaugurate.Inaugurate(config.RABBIT_MQ_DIRECTORY)
imageStore = imagestore.ImageStore()
buildImageThread = buildimagethread.BuildImageThread(
    inaugurate=inaugurateInstance, tftpboot=tftpbootInstance, dnsmasq=dnsmasqInstance,
    imageStore=imageStore, reclaimHost=reclaimHost)
publishInstance = publish.Publish("ampq://localhost:%d/%%2F" % inaugurator.server.config.PORT)
allVMs = dict()
allocationsInstance = allocations.Allocations(
    dnsmasq=dnsmasqInstance, broadcaster=publishInstance, buildImageThread=buildImageThread,
    imageStore=imageStore, allVMs=allVMs)
ipcServer = ipcserver.IPCServer(dnsmasq=dnsmasqInstance, allocations=allocationsInstance)


def serialLogFilename(vmID):
    vms = {"rackattack-vm%d" % k: v for k, v in allVMs.iteritems()}
    return vms[vmID].serialLogFilename()


def createPostMortemPackForAllocationID(allocationID):
    with globallock.lock():
        return allocationsInstance.byIndex(int(allocationID)).createPostMortemPack()


root = httprootresource.HTTPRootResource(
    serialLogFilename, createPostMortemPackForAllocationID,
    config.MANAGED_POST_MORTEM_PACKS_DIRECTORY)
reactor.listenTCP(args.httpPort, server.Site(root))
reactor.listenTCP(args.requestPort, transportserver.TransportFactory(ipcServer.handle))
logging.info("Virtual RackAttack up and running")
reactor.run()
