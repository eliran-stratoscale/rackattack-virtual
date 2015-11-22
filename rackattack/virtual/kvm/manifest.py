import os.path
import xmltodict
from rackattack.virtual.kvm import config


class Manifest:
    def __init__(self, xml):
        self._dict = xmltodict.parse(xml)

    def xml(self):
        return xmltodict.unparse(self._dict)

    def name(self):
        return self._dict['domain']['name']

    def vcpus(self):
        return int(self._dict['domain']['vcpu']['#text'])

    def memoryMB(self):
        assert self._dict['domain']['currentMemory']['@unit'] == "KiB"
        return int(self._dict['domain']['currentMemory']['#text']) / 1024

    def primaryMACAddress(self):
        return self._dict['domain']['devices']['interface'][0]['mac']['@address']

    def secondaryMACAddress(self):
        return self._dict['domain']['devices']['interface'][1]['mac']['@address']

    def disk1Image(self):
        return self._dict['domain']['devices']['disk'][0]['source']['@file']

    def disk2Image(self):
        return self._dict['domain']['devices']['disk'][1]['source']['@file']

    @classmethod
    def _findEmulatorPath(cls):
        possiblePaths = ("/usr/bin/qemu-kvm", "/usr/libexec/qemu-kvm")
        for _path in possiblePaths:
            if os.path.exists(_path):
                return _path
        return Exception("No QEMU-KVM emulator found")

    @classmethod
    def create(cls,
               name,
               memoryMB,
               vcpus,
               disk1Image,
               disk2Image,
               primaryMACAddress,
               secondaryMACAddress,
               networkName,
               serialOutputFilename,
               bootFromNetwork):
        assert name.startswith(config.DOMAIN_PREFIX)
        assert memoryMB > 0
        assert vcpus >= 1
        emulatorPath = cls._findEmulatorPath()
        return cls(_TEMPLATE % dict(
            name=name,
            memoryKB=memoryMB * 1024,
            vcpus=vcpus,
            disk1Image=disk1Image,
            disk2Image=disk2Image,
            primaryMACAddress=primaryMACAddress,
            secondaryMACAddress=secondaryMACAddress,
            networkName=config.NETWORK_NAME,
            serialOutputFilename=serialOutputFilename,
            bootDevice='network' if bootFromNetwork else 'hd',
            emulatorPath=emulatorPath))

_TEMPLATE = """
<domain type='kvm'>
  <name>%(name)s</name>
  <memory unit='KiB'>%(memoryKB)d</memory>
  <currentMemory unit='KiB'>%(memoryKB)d</currentMemory>
  <vcpu placement='static'>%(vcpus)d</vcpu>
  <os>
    <type arch='x86_64' machine='pc'>hvm</type>
    <boot dev='%(bootDevice)s'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <cpu mode='host-model'>
    <model fallback='allow'/>
  </cpu>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <emulator>%(emulatorPath)s</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='writeback' io='threads'/>
      <source file='%(disk1Image)s'/>
      <target dev='vda' bus='virtio'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x04' function='0x0'/>
    </disk>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='writeback' io='threads'/>
      <source file='%(disk2Image)s'/>
      <target dev='vdb' bus='virtio'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x06' function='0x0'/>
    </disk>
    <controller type='usb' index='0'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x01' function='0x2'/>
    </controller>
    <controller type='pci' index='0' model='pci-root'/>
    <interface type='network'>
      <mac address='%(primaryMACAddress)s'/>
      <source network='%(networkName)s'/>
      <model type='virtio'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
    </interface>
    <interface type='network'>
      <mac address='%(secondaryMACAddress)s'/>
      <source network='%(networkName)s'/>
      <model type='virtio'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x07' function='0x0'/>
    </interface>
    <serial type='file'>
      <source path='%(serialOutputFilename)s'/>
      <target port='0'/>
    </serial>
    <console type='file'>
      <source path='%(serialOutputFilename)s'/>
      <target type='serial' port='0'/>
    </console>
    <input type='mouse' bus='ps2'/>
    <graphics type='vnc' port='-1' autoport='yes'/>
    <video>
      <model type='cirrus' vram='9216' heads='1'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x02' function='0x0'/>
    </video>
    <memballoon model='virtio'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x05' function='0x0'/>
    </memballoon>
  </devices>
</domain>
"""
