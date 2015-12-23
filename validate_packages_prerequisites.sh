#!/bin/bash

# Determine package manager
YUM_CMD=$(which yum)
APT_GET_CMD=$(which apt-get)
if [[ "$YUM_CMD" != "" ]]; then
sudo yum install -y libvirt libvirt-devel libvirt-daemon-kvm syslinux-tftpboot device-mapper-libs qemu-kvm;
sudo yum upgrade -y "device-mapper-libs";
rpm --import https://www.rabbitmq.com/rabbitmq-signing-key-public.asc;
sudo yum install -y --nogpg rabbitmq-server;
elif [[ "$APT_GET_CMD" != "" ]]; then
sudo apt-get -y install libvirt-bin libvirt-dev syslinux rabbitmq-server;
else
echo "Error: Package manager was not found. Cannot continue with the installation.";
exit 1;
fi