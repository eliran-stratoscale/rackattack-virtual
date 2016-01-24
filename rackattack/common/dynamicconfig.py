import yaml
import logging
from rackattack.common import config
from rackattack.common import hoststatemachine


STATE_MACHINE_CONFIG_SCHEME = dict(NR_CONSECUTIVE_ERRORS_BEFORE_DESTRUCTION=int,
                                   NR_CONSECUTIVE_ERRORS_BEFORE_RECONFIGURING_BIOS=int,
                                   NR_CONSECUTIVE_ERRORS_BEFORE_CLEARING_DISK=int,
                                   NR_CONSECUTIVE_ERRORS_BEFORE_HARD_RESET=int,
                                   MAX_NR_CONSECUTIVE_INAUGURATION_FAILURES=int,
                                   ALLOW_CLEARING_OF_DISK=bool,
                                   HOSTS_MAX_UPTIME=int)
CONFIGURABLE_STATE_MACHINE_TIMEOUTS = ("STATE_SOFT_RECLAMATION",
                                       "STATE_COLD_RECLAMATION",
                                       "STATE_INAUGURATION_LABEL_PROVIDED")


def _setAttributes(obj, attributes, config):
    for attrName, attrType in attributes.iteritems():
        if not hasattr(obj, attrName):
            logging.error("Invalid attribute in configuration: '%(attrName)s'", dict(attrName=attrName))
            raise ValueError(attrName)
        if attrName not in config:
            logging.warn("Skipping configuration of: '%(attrName)s'", dict(attrName=attrName))
            continue
        attrValue = config[attrName]
        if not isinstance(attrValue, attrType):
            logging.error("Invalid configuration: %(attrName)s should be of type %(attrType)s",
                          dict(attrName=attrName, attrType=attrType))
            raise ValueError(attrValue)
        setattr(obj, attrName, attrValue)


def _printAttributes(obj, attrNames):
    for name in attrNames:
        value = getattr(obj, name)
        logging.info("%(obj)s.%(name)s: %(value)s", dict(obj=obj, name=name, value=value))


def printConfiguration():
    logging.info("The following is the current state machine configuration:")
    _printAttributes(hoststatemachine.HostStateMachine, STATE_MACHINE_CONFIG_SCHEME.keys())
    for stateName in CONFIGURABLE_STATE_MACHINE_TIMEOUTS:
        state = getattr(hoststatemachine, stateName)
        timeout = hoststatemachine.HostStateMachine.TIMEOUT[state]
        logging.info("%(stateName)s: %(timeout)s", dict(stateName=stateName, timeout=timeout))


def reloadConfiguration():
    logging.info("Reloading state machine configuration...")
    global config
    with open(config.STATE_MACHINE_CONFIGURATION_PATH) as f:
        configFile = yaml.load(f)
        _setAttributes(hoststatemachine.HostStateMachine, STATE_MACHINE_CONFIG_SCHEME, configFile)
        timeouts = hoststatemachine.HostStateMachine.TIMEOUT
        for stateName in CONFIGURABLE_STATE_MACHINE_TIMEOUTS:
            state = getattr(hoststatemachine, stateName)
            timeout = configFile["TIMEOUTS"][stateName]
            hoststatemachine.HostStateMachine.TIMEOUT[state] = timeout
    logging.info("Done reloading.")
    printConfiguration()
