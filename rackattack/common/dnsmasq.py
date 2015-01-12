import logging
import subprocess
import tempfile
import threading
import atexit
import time
import signal
import os
import re


class DNSMasq(threading.Thread):
    @classmethod
    def eraseLeasesFile(self):
        LEASES_FILE = '/var/lib/dnsmasq/dnsmasq.leases'
        if os.path.exists(LEASES_FILE):
            logging.info("Erasing old leases file")
            os.unlink(LEASES_FILE)

    @classmethod
    def killAllPrevious(self):
        logging.info("Killing all previous instances of dnsmasq")
        while True:
            try:
                subprocess.check_output(
                    ["killall", "dnsmasq"], close_fds=True, stderr=subprocess.STDOUT)
                time.sleep(0.1)
            except:
                logging.info("Done killing previous instances of dnsmasq")
                return

    @classmethod
    def killSpecificPrevious(self, serverIP):
        logging.info("Killing all previous instances of dnsmasq bound to %(ip)s", dict(ip=serverIP))
        lines = subprocess.check_output(["netstat", "-l", "-u", "-p", "-n"]).strip().split('\n')
        pid = None
        for line in lines:
            if serverIP + ":53" not in line:
                continue
            if '/dnsmasq' not in line:
                continue
            pid = re.search(r'(\d+)/dnsmasq', line).group(1)
        if pid is None:
            logging.info("Previous instance not found, not killing anything")
            return
        while True:
            try:
                subprocess.check_output(["kill", pid], close_fds=True, stderr=subprocess.STDOUT)
                time.sleep(0.1)
            except:
                logging.info("Done killing previous instance of dnsmasq %(pid)s", dict(pid=pid))
                return

    def __init__(
            self, tftpboot, serverIP, netmask, firstIP, lastIP, gateway=None,
            nameserver=None, interface=None):
        self._tftpboot = tftpboot
        self._nodesMACIPPairs = []
        self._netmask = netmask
        self._firstIP = firstIP
        self._lastIP = lastIP
        self._gateway = gateway
        self._nameserver = nameserver
        self._interface = interface
        self._logFile = tempfile.NamedTemporaryFile(suffix=".dnsmasq.log")
        self._configFile = self._configurationFile()
        self._hostsFile = tempfile.NamedTemporaryFile(suffix=".dnsmasq.hosts")
        self._writeHostsFile()
        self._stopped = False
        self._popen = subprocess.Popen(
            ['dnsmasq', '--no-daemon', '--listen-address=' + serverIP,
                '--conf-file=' + self._configFile.name, '--dhcp-hostsfile=' + self._hostsFile.name],
            stdout=self._logFile, stderr=subprocess.STDOUT, close_fds=True)
        atexit.register(self._exit)
        threading.Thread.__init__(self)
        self.daemon = True
        threading.Thread.start(self)

    def _reload(self):
        self._writeHostsFile()
        os.kill(self._popen.pid, signal.SIGHUP)

    def add(self, mac, ip):
        self._nodesMACIPPairs.append((mac, ip))
        self._reload()

    def remove(self, mac):
        self._nodesMACIPPairs = [(entryMac, entryIp)
                                 for (entryMac, entryIp) in self._nodesMACIPPairs if entryMac != mac]
        self._reload()

    def _writeHostsFile(self):
        hosts = ['%s,%s,infinite' % (mac.lower(), ip) for mac, ip in self._nodesMACIPPairs]
        self._hostsFile.seek(0)
        self._hostsFile.truncate()
        self._hostsFile.write("\n".join(hosts))
        self._hostsFile.flush()

    def _configurationFile(self):
        conf = tempfile.NamedTemporaryFile(suffix=".dnsmasq.conf")
        gateway = 'dhcp-option=option:router,%s' % self._gateway if self._gateway is not None else ""
        nameserver = 'dhcp-option=6,%s' % self._nameserver if self._nameserver is not None else ""
        interface = "" if self._interface is None else "bind-interfaces\ninterface=" + self._interface
        output = _TEMPLATE % dict(
            netmask=self._netmask, gateway=gateway, nameserver=nameserver, interface=interface,
            tftpbootRoot=self._tftpboot.root(), firstIPAddress=self._firstIP, lastIPAddress=self._lastIP)
        conf.write(output)
        conf.flush()
        return conf

    def run(self):
        self._popen.wait()
        if self._stopped:
            return
        self._stopped = True
        logging.error("DNSMASQ process exited early, shutting down")
        logging.error("DNSMASQ output:\n%(output)s", dict(output=open(self._logFile.name).read()))
        os.system("cp %s /tmp/dnsmasq.error.log" % self._logFile.name)
        os.system("cp %s /tmp/dnsmasq.error.config" % self._configFile.name)
        os.kill(os.getpid(), signal.SIGKILL)

    def _exit(self):
        if self._stopped:
            return
        self._stopped = True
        self._popen.terminate()

_TEMPLATE = \
    'tftp-root=%(tftpbootRoot)s\n' + \
    '%(interface)s\n' + \
    'except-interface=lo\n' + \
    'enable-tftp\n' + \
    'dhcp-boot=pxelinux.0\n' + \
    'dhcp-option=vendor:PXEClient,6,2b\n' + \
    'dhcp-no-override\n' + \
    '%(gateway)s\n' + \
    '%(nameserver)s\n' + \
    'dhcp-ignore=tag:!known\n' + \
    'pxe-prompt="Press F8 for boot menu", 1\n' + \
    'pxe-service=X86PC, "Boot from network", pxelinux\n' + \
    'pxe-service=X86PC, "Boot from local hard disk", 0\n' + \
    'dhcp-range=%(firstIPAddress)s,%(lastIPAddress)s,%(netmask)s,12h\n'
