import os
from rackattack.common.tests.fakepipes import FakePipeMethods, FakePipe, FakeNamedPipe


def enable(modulesInWhichToSetupMocks, fakeFilesystem):
    methodsMock = FakePipeMethods(modulesInWhichToSetupMocks, fakeFilesystem)
    return methodsMock


def disable(*moduleInWhichToRestoreMethods):
    FakePipeMethods.disable(moduleInWhichToRestoreMethods)
