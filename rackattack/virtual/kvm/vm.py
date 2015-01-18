from rackattack.virtual.kvm import manifest
from rackattack.virtual.kvm import libvirtsingleton
from rackattack.virtual.kvm import config
from rackattack.virtual.kvm import network
from rackattack.virtual.kvm import imagecommands
import os
import logging


class VM:
    def __init__(
            self, index, requirement, domain,
            manifest, disk1SizeGB, disk2SizeGB):
        self._index = index
        self._requirement = requirement
        self._domain = domain
        self._manifest = manifest
        self._disk1SizeGB = disk1SizeGB
        self._disk2SizeGB = disk2SizeGB

    def index(self):
        return self._index

    def id(self):
        return self._nameFromIndex(self._index)

    def primaryMACAddress(self):
        return network.primaryMACAddressFromVMIndex(self._index)

    def secondaryMACAddress(self):
        return network.secondMACAddressFromVMIndex(self._index)

    def ipAddress(self):
        return network.ipAddressFromVMIndex(self._index)

    def rootSSHCredentials(self):
        return dict(hostname=self.ipAddress(), username="root", password=config.ROOT_PASSWORD, port=22)

    def coldRestart(self):
        with libvirtsingleton.it().lock():
            self._domain.destroy()
            self._domain.create()

    def reconfigureBIOS(self):
        logging.warning("Should not be called for VM")

    def destroy(self):
        with libvirtsingleton.it().lock():
            self._domain.destroy()
            self._domain.undefine()
        if os.path.exists(self._manifest.disk1Image()):
            os.unlink(self._manifest.disk1Image())
        os.unlink(self._manifest.disk2Image())

    def disk1Image(self):
        return self._manifest.disk1Image()

    def serialLogFilename(self):
        name = self._nameFromIndex(self._index)
        return os.path.join(config.SERIAL_LOGS_DIRECTORY, name + ".serial.txt")

    @classmethod
    def createFromImageStore(cls, index, requirement, imageStore):
        name = cls._nameFromIndex(index)
        image1 = os.path.join(config.DISK_IMAGES_DIRECTORY, name + "_disk1.qcow2")
        frozenImage = imageStore.get(
            sizeGB=requirement['hardwareConstraints']['minimumDisk1SizeGB'],
            imageLabel=requirement['imageLabel'])
        if not os.path.isdir(os.path.dirname(image1)):
            os.makedirs(os.path.dirname(image1))
        imagecommands.deriveCopyOnWrite(original=frozenImage, newImage=image1)
        return cls._createFromGivenImage(index, requirement, image1, False)

    @classmethod
    def createFromNewImage(cls, index, requirement):
        name = cls._nameFromIndex(index)
        image1 = os.path.join(config.DISK_IMAGES_DIRECTORY, name + "_disk1.qcow2")
        if not os.path.isdir(os.path.dirname(image1)):
            os.makedirs(os.path.dirname(image1))
        imagecommands.create(
            image=image1, sizeGB=requirement['hardwareConstraints']['minimumDisk1SizeGB'])
        return cls._createFromGivenImage(index, requirement, image1, True)

    @classmethod
    def _createFromGivenImage(cls, index, requirement, image1, bootFromNetwork):
        name = cls._nameFromIndex(index)
        image2 = os.path.join(config.DISK_IMAGES_DIRECTORY, name + "_disk2.qcow2")
        serialLog = os.path.join(config.SERIAL_LOGS_DIRECTORY, name + ".serial.txt")
        if not os.path.isdir(os.path.dirname(serialLog)):
            os.makedirs(os.path.dirname(serialLog))
        hardwareConstraints = requirement['hardwareConstraints']
        imagecommands.create(
            image=image2, sizeGB=hardwareConstraints['minimumDisk2SizeGB'])
        mani = manifest.Manifest.create(
            name=name,
            memoryMB=int(1024 * hardwareConstraints['minimumRAMGB']),
            vcpus=hardwareConstraints['minimumCPUs'],
            disk1Image=image1,
            disk2Image=image2,
            primaryMACAddress=network.primaryMACAddressFromVMIndex(index),
            secondaryMACAddress=network.secondMACAddressFromVMIndex(index),
            networkName=network.NAME,
            serialOutputFilename=serialLog,
            bootFromNetwork=bootFromNetwork)
        with libvirtsingleton.it().lock():
            domain = libvirtsingleton.it().libvirt().defineXML(mani.xml())
            domain.create()
        return cls(
            index=index, domain=domain, requirement=requirement, manifest=mani,
            disk1SizeGB=hardwareConstraints['minimumDisk1SizeGB'],
            disk2SizeGB=hardwareConstraints['minimumDisk2SizeGB'])

    @classmethod
    def _nameFromIndex(cls, index):
        return "rackattack-vm%d" % index
