import os
from rackattack.common.tests.fakepipes import FakePipeMethods, FakePipe, FakeNamedPipe


def enable(moduleInWhichToSetupMocks, fakeFilesystem):
    methodsMock = FakePipeMethods(moduleInWhichToSetupMocks, fakeFilesystem)
    return methodsMock


def disable(moduleInWhichToRestoreMethods):
    FakePipeMethods.disable(moduleInWhichToRestoreMethods)
