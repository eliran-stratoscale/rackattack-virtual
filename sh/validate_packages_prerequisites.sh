#!/bin/bash

# Determine package manager
YUM_CMD=$(which yum)
APT_GET_CMD=$(which apt-get)
if [[ "$YUM_CMD" != "" ]]; then
sudo yum install -y libvirt libvirt-devel libvirt-daemon-kvm syslinux-tftpboot device-mapper-libs qemu-kvm net-tools;
sudo yum upgrade -y "device-mapper-libs";
sudo rpm --import https://www.rabbitmq.com/rabbitmq-signing-key-public.asc;
sudo yum install -y --nogpg rabbitmq-server;
elif [[ "$APT_GET_CMD" != "" ]]; then
sudo apt-get -y install libvirt-bin libvirt-dev syslinux pxelinux rabbitmq-server qemu-kvm net-tools;
sudo systemctl stop rabbitmq-server
sudo systemctl disable rabbitmq-server
else
echo "Error: Package manager was not found. Cannot continue with the installation.";
exit 1;
fi
which solvent > /dev/null || (echo "Error: solvent was not found. Please install it first." && exit 1)

./sh/install_inaugurator.sh
