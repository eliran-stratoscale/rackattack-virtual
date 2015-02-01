import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
from rackattack.ssh import connection
connection.discardParamikoLogs()
connection.discardSSHDebugMessages()
import time
import argparse
from rackattack.virtual import ipcserver
from rackattack.virtual import buildimagethread
from rackattack.virtual.kvm import cleanup
import rackattack.virtual.handlekill
from rackattack.virtual.kvm import config
from rackattack.virtual.kvm import network
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
import atexit

parser = argparse.ArgumentParser()
parser.add_argument("--requestPort", default=1014, type=int)
parser.add_argument("--subscribePort", default=1015, type=int)
parser.add_argument("--httpPort", default=1016, type=int)
parser.add_argument("--maximumVMs", type=int)
parser.add_argument("--diskImagesDirectory")
parser.add_argument("--serialLogsDirectory")
parser.add_argument("--managedPostMortemPacksDirectory")
args = parser.parse_args()

if args.maximumVMs:
    config.MAXIMUM_VMS = args.maximumVMs
if args.diskImagesDirectory:
    config.DISK_IMAGES_DIRECTORY = args.diskImagesDirectory
if args.serialLogsDirectory:
    config.SERIAL_LOGS_DIRECTORY = args.serialLogsDirectory
if args.managedPostMortemPacksDirectory:
    config.MANAGED_POST_MORTEM_PACKS_DIRECTORY = args.managedPostMortemPacksDirectory

cleanup.cleanup()
atexit.register(cleanup.cleanup)
timer.TimersThread()
network.setUp()
tftpbootInstance = tftpboot.TFTPBoot(
    netmask=network.NETMASK,
    inauguratorServerIP=network.GATEWAY_IP_ADDRESS,
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
for mac, ip in network.allNodesMACIPPairs():
    dnsmasqInstance.add(mac, ip)
inaugurateInstance = inaugurate.Inaugurate(bindHostname=network.GATEWAY_IP_ADDRESS)
imageStore = imagestore.ImageStore()
buildImageThread = buildimagethread.BuildImageThread(
    inaugurate=inaugurateInstance, tftpboot=tftpbootInstance, dnsmasq=dnsmasqInstance,
    imageStore=imageStore)
publishFactory = publish.PublishFactory()
publishInstance = publish.Publish(publishFactory)
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
reactor.listenTCP(args.subscribePort, publishFactory)
logging.info("Virtual RackAttack up and running")
reactor.run()
