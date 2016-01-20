import os
import shutil
import atexit
import logging


INAUGURATOR_KERNEL = "/usr/share/inaugurator/inaugurator.vmlinuz"
INAUGURATOR_INITRD = "/usr/share/inaugurator/inaugurator.thin.initrd.img"
ROOT_PATH = "/var/lib/rackattack/pxeboot"


class TFTPBoot:
    def __init__(
            self, netmask, inauguratorServerIP, inauguratorServerPort, inauguratorGatewayIP,
            osmosisServerIP, rootPassword, withLocalObjectStore):
        self._netmask = netmask
        self._inauguratorServerIP = inauguratorServerIP
        self._inauguratorServerPort = inauguratorServerPort
        self._inauguratorGatewayIP = inauguratorGatewayIP
        self._osmosisServerIP = osmosisServerIP
        self._withLocalObjectStore = withLocalObjectStore
        self._root = ROOT_PATH
        if os.path.exists(self._root):
            shutil.rmtree(self._root)
        os.makedirs(self._root)
        self._rootPassword = rootPassword
        atexit.register(self._cleanup)
        self._pxelinuxConfigDir = os.path.join(self._root, "pxelinux.cfg")
        self._installPXELinux()

    def root(self):
        return self._root

    def _cleanup(self):
        shutil.rmtree(self._root, ignore_errors=True)

    def _installPXELinux(self):
        if os.path.exists("/usr/share/syslinux/menu.c32"):
            shutil.copy("/usr/share/syslinux/menu.c32", self._root)
            shutil.copy("/usr/share/syslinux/chain.c32", self._root)
            if os.path.exists("/usr/share/syslinux/libutil.c32"):
                shutil.copy("/usr/share/syslinux/libutil.c32", self._root)
                shutil.copy("/usr/share/syslinux/ldlinux.c32", self._root)
        else:
            shutil.copy("/usr/lib/syslinux/modules/bios/menu.c32", self._root)
            shutil.copy("/usr/lib/syslinux/modules/bios/chain.c32", self._root)
            shutil.copy("/usr/lib/syslinux/modules/bios/ldlinux.c32", self._root)
            shutil.copy("/usr/lib/syslinux/modules/bios/libutil.c32", self._root)
        if os.path.exists("/usr/share/syslinux/pxelinux.0"):
            shutil.copy("/usr/share/syslinux/pxelinux.0", self._root)
        else:
            shutil.copy("/usr/lib/PXELINUX/pxelinux.0", self._root)
        shutil.copy(INAUGURATOR_KERNEL, self._root)
        shutil.copy(INAUGURATOR_INITRD, self._root)
        os.mkdir(self._pxelinuxConfigDir)

    def configureForInaugurator(self, id, mac, ip, clearDisk=False, targetDevice=None):
        if clearDisk:
            logging.info("Configuring %(id)s host %(ipAddress)s inaugurator to clearDisk", dict(
                id=id, ipAddress=ip))
        self._writeConfiguration(mac, self._configurationForInaugurator(id,
                                                                        mac,
                                                                        ip,
                                                                        clearDisk=clearDisk,
                                                                        targetDevice=targetDevice))

    def configureForLocalBoot(self, mac):
        self._writeConfiguration(mac, _CONFIGURATION_FOR_LOCAL_BOOT)

    def _writeConfiguration(self, mac, contents):
        basename = '01-' + mac.replace(':', '-')
        path = os.path.join(self._pxelinuxConfigDir, basename)
        with open(path, "w") as f:
            f.write(contents)

    def _configurationForInaugurator(self, id, mac, ip, clearDisk, targetDevice=None):
        return _INAUGURATOR_TEMPLATE % dict(
            inauguratorCommandLine=self.inauguratorCommandLine(id, mac, ip, clearDisk, targetDevice),
            inauguratorKernel=os.path.basename(INAUGURATOR_KERNEL),
            inauguratorInitrd=os.path.basename(INAUGURATOR_INITRD))

    def inauguratorCommandLine(self, id, mac, ip, clearDisk, targetDevice=None):
        result = _INAUGURATOR_COMMAND_LINE % dict(
            macAddress=mac, ipAddress=ip, netmask=self._netmask,
            osmosisServerIP=self._osmosisServerIP, inauguratorServerIP=self._inauguratorServerIP,
            inauguratorServerPort=self._inauguratorServerPort,
            inauguratorGatewayIP=self._inauguratorGatewayIP,
            rootPassword=self._rootPassword,
            id=id)
        if targetDevice is None:
            logging.info("Not setting target device for inauguration")
        else:
            logging.info("Setting target device for inauguration: %(targetDevice)s",
                         dict(targetDevice=targetDevice))
            result += _INAUGURATOR_COMMAND_LINE_TARGET_DEVICE_ADDITION % dict(targetDevice=targetDevice)
            logging.info("Inaugurator command line: %(cmd)s", dict(cmd=result))
        if self._withLocalObjectStore:
            result += " --inauguratorWithLocalObjectStore"
        if clearDisk:
            result += " --inauguratorClearDisk"
        return result


_INAUGURATOR_TEMPLATE = r"""
#serial support on port0 (COM1) running baud-rate 115200
SERIAL 0 115200
#VGA output parallel to serial disabled
CONSOLE 0

default menu.c32
prompt 0
timeout 1

menu title RackAttack PXE Boot Menu - Inaugurator

label Latest
    menu label Latest
    kernel %(inauguratorKernel)s
    initrd %(inauguratorInitrd)s
    append %(inauguratorCommandLine)s
"""

_CONFIGURATION_FOR_LOCAL_BOOT = """
#serial support on port0 (COM1) running baud-rate 115200
SERIAL 0 115200
#VGA output parallel to serial disabled
CONSOLE 0

default menu.c32
prompt 0
timeout 1

menu title RackAttack PXE Boot Menu - Local Disk

label BootFromLocalDisk
    menu label BootFromLocalDisk
    COM32 chain.c32
    APPEND hd0
"""

_INAUGURATOR_COMMAND_LINE = \
    "console=ttyS0,115200n8 edd=off " \
    "--inauguratorSource=network " \
    "--inauguratorUseNICWithMAC=%(macAddress)s --inauguratorOsmosisObjectStores=%(osmosisServerIP)s:1010 " \
    "--inauguratorServerAMQPURL=amqp://guest:guest@%(inauguratorServerIP)s:%(inauguratorServerPort)s/%%2F " \
    "--inauguratorMyIDForServer=%(id)s " \
    "--inauguratorIPAddress=%(ipAddress)s " \
    "--inauguratorNetmask=%(netmask)s --inauguratorGateway=%(inauguratorGatewayIP)s " \
    "--inauguratorChangeRootPassword=%(rootPassword)s"

_INAUGURATOR_COMMAND_LINE_TARGET_DEVICE_ADDITION = " --inauguratorTargetDeviceCandidate=%(targetDevice)s"
