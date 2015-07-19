import logging
from rackattack.ssh import connection
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
connection.discardParamikoLogs()
connection.discardSSHDebugMessages()
logging.getLogger('pika').setLevel(logging.INFO)
