class Hosts:
    def __init__(self):
        self._stateMachines = []

    def add(self, stateMachine):
        self._stateMachines.append(stateMachine)

    def byID(self, id):
        for stateMachine in self._stateMachines:
            if stateMachine.hostImplementation().id() == id:
                return stateMachine
        raise Exception("Host with ID '%s' was not found" % id)

    def destroy(self, stateMachine):
        self._stateMachines.remove(stateMachine)

    def all(self):
        return self._stateMachines

    def availableIndex(self):
        indices = set(xrange(1, len(self._stateMachines) + 2))
        for stateMachine in self._stateMachines:
            indices.discard(stateMachine.hostImplementation().index())
        return min(indices)
