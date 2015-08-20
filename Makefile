all: unittest build check_convention

clean:
	sudo rm -fr build images.fortests

UNITTESTS=$(shell find rackattack -name 'test_*.py' | sed 's@/@.@g' | sed 's/\(.*\)\.py/\1/' | sort)
COVERED_FILES=rackattack/common/hoststatemachine.py,rackattack/common/hosts.py,rackattack/common/dnsmasq.py,rackattack/common/inaugurate.py,rackattack/common/reclaimhostspooler.py
unittest:
	UPSETO_JOIN_PYTHON_NAMESPACES=Yes PYTHONPATH=. python -m coverage run -m unittest $(UNITTESTS)
	python -m coverage report --show-missing --rcfile=coverage.config --fail-under=77 --include=$(COVERED_FILES)

WHITEBOXTESTS=$(shell find tests -name 'test?_*.py' | sed 's@/@.@g' | sed 's/\(.*\)\.py/\1/' | sort)
whiteboxtest_nonstandard:
	UPSETO_JOIN_PYTHON_NAMESPACES=Yes PYTHONPATH=. python -m unittest $(WHITEBOXTESTS)

testone:
	UPSETO_JOIN_PYTHON_NAMESPACES=Yes PYTHONPATH=. python tests/test$(NUMBER)_*.py

check_convention:
	pep8 rackattack --max-line-length=109

.PHONY: build
build: build/rackattack.virtual.egg

build/rackattack.virtual.egg: rackattack/virtual/main.py
	-mkdir $(@D)
	python -m upseto.packegg --entryPoint=$< --output=$@ --createDeps=$@.dep --compile_pyc --joinPythonNamespaces
-include build/rackattack.virtual.egg.dep

install: build/rackattack.virtual.egg
	-sudo service rackattack-virtual stop
	-sudo systemctl stop rackattack-virtual.service
	-sudo mkdir /usr/share/rackattack.virtual
	sudo cp build/rackattack.virtual.egg /usr/share/rackattack.virtual
	if grep -i ubuntu /etc/os-release >/dev/null 2>/dev/null; then make install_service_upstart; else make install_service_systemd; fi

install_service_systemd:
	sudo cp rackattack-virtual.service /usr/lib/systemd/system/rackattack-virtual.service
	sudo systemctl enable rackattack-virtual.service
	if ["$(DONT_START_SERVICE)" == ""]; then sudo systemctl start rackattack-virtual; fi

install_service_upstart:
	sudo cp upstart_rackattack-virtual.conf /etc/init/rackattack-virtual.conf
	if ["$(DONT_START_SERVICE)" == ""]; then sudo service rackattack-virtual start; fi

uninstall:
	-sudo service rackattack-virtual stop
	-sudo systemctl stop rackattack-virtual
	-sudo systemctl disable rackattack-virtual.service
	-sudo rm -fr /usr/lib/systemd/system/rackattack-virtual.service /etc/init/rackattack-virtual.conf
	sudo rm -fr /usr/share/rackattack.virtual

prepareForCleanBuild:
	cd ../upseto ; make install
