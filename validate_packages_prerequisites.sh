# Determine package manager
YUM_CMD=$(which yum)
APT_GET_CMD=$(which apt-get)
if [[ ! -z $YUM_CMD ]]; then
sudo yum install -y libvirt libvirt-devel libvirt-daemon-kvm syslinux-tftpboot device-mapper-libs rabbitmq-server qemu-kvm
sudo yum upgrade -y "device-mapper-libs"                                      
rpm --import https://www.rabbitmq.com/rabbitmq-signing-key-public.asc
sudo yum install --nogpg rabbitmq-server
elif [[ ! -z $APT_GET_CMD ]]; then
	echo "Nothing to be done yet for apt based packages."
else
    echo "Error: Package manager was not found."                                                             
    exit 1;                                                                                                  
fi
