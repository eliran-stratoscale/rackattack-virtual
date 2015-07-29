import sys
import fake_tempfile
import fake_filesystem
import fake_filesystem_glob
import fake_filesystem_shutil


fakeModules = dict(os=fake_filesystem.FakeOsModule,
                   glob=fake_filesystem_glob.FakeGlobModule,
                   shutil=fake_filesystem_shutil.FakeShutilModule,
                   tempfile=fake_tempfile.FakeTempfileModule)
fakeModules["os.path"] = fake_filesystem.FakePathModule
fakeFunctions = dict(open=fake_filesystem.FakeFileOpen)


def enableMockedFilesystem(testedModule):
    fakeFilesystem = fake_filesystem.FakeFilesystem()
    for moduleName, fakeModuleGenerationMethod in fakeModules.iteritems():
        fakeModule = fakeModuleGenerationMethod(fakeFilesystem)
        setattr(testedModule, moduleName, fakeModule)
    for functionName, fakeFunctionGenerationMethod in fakeFunctions.iteritems():
        fakeFunction = fakeFunctionGenerationMethod(fakeFilesystem)
        setattr(testedModule, functionName, fakeFunction)
    return fakeFilesystem


def disableMockedFilesystem(testedModule):
    for moduleName in fakeModules:
        setattr(testedModule, moduleName, sys.modules[moduleName])
    for functionName in fakeFunctions:
        setattr(testedModule, functionName, getattr(sys.modules["__builtin__"], functionName))
