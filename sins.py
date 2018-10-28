'''
TODO Handle allocation no_acknowledgemnt
TODO Handle proper network stop (stop packet + ack)
'''

import simpy

from async_communication import AsyncCommunication


# A generic Network Agent.
class Agent:
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        self.env = simpy.rt.RealtimeEnvironment() if env is None else env
        self.running = self.env.process(self._run())

    def run(self):
        self.env.run(until=self.running)

    def _run(self):
        if isinstance(self.env, simpy.RealtimeEnvironment):
            self.env.sync()
        while True:
            try:
                yield self.env.timeout(1000)
            except simpy.Interrupt:
                return

    def schedule(self, action, args=None, time=0):
        """ The agent's schedule function

        :param time: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :returns:
        :rtype:

        """
        print("scheduling action {}".format(action))
        return self.env.process(
            self.process(action=action, args=args, time=time))

    def process(self, action, args, time=0):
        yield self.env.timeout(time)
        print("executing action {} after {} seconds".format(action, time))
        if args is None:
            action()
        else:
            action(**args)

    def stop(self):
        """ stop the Agent by stop the local simpy environment.

        :returns:
        :rtype:

        """
        self.running.interrupt()


class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator

    def __init__(self, local='*:5555', env=None):
        self.local = local
        self.comm = AsyncCommunication()
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.loads = {}
        self.timeouts = {}
        self.alloc_ack_timeout = 10
        super(NetworkAllocator, self).__init__(env=env)

    def initialise(self):
        pass

    def receive_handle(self, data, src):
        """ Handle packets received and decoded at the AsyncCommunication layer.

        :param data: received payload
        :param src: source of payload
        :returns:
        :rtype:

        """
        msg_type = data['msg_type']
        if msg_type == 'join':
            agent_id = data['agent_id']
            allocation = data['allocation']
            self.add_load(load_id=agent_id, allocation=allocation)
            self.schedule(action=self.send_join_ack, args={'dst': src})
        elif msg_type == 'allocation_ack':
            agent_id = data['agent_id']
            allocation = data['allocation']
            self.add_load(load_id=agent_id, allocation=allocation)
            # Interrupting timeout event for this allocation
            id = allocation['allocation_id']
            self.timeouts.pop(id, None).interrupt()
        elif msg_type == 'leave':
            agent_id = data['agent_id']
            self.remove_load(load_id=agent_id)

    def add_load(self, load_id, allocation):
        """ Add a network load to Allocator's known loads list.

        :param load_id: id of load to be added (used as a dictionary key)
        :param allocation: the load's reported allocation when added.
        :returns:
        :rtype:

        """
        self.loads[load_id] = allocation

    def remove_load(self, load_id):
        """ Remove a load from Allocator's known loads list.

        :param load_id: id (key) of load to be removed.
        :returns: The removed load.
        :rtype:

        """
        return self.loads.pop(load_id, None)

    def send_allocation(self, agent_id, allocation):
        """ Send an allocation to a Network's load

        :param agent_id: id of destination load
        :param allocation: allocation to be sent
        :returns:
        :rtype:

        """
        print("sending allocation to {}".format(agent_id))
        packet = {'msg_type': 'allocation', 'allocation': allocation}

        # Creating Event that is triggered if no ack is received before a timeout
        noack_event = self.env.event()
        noack_event.callbacks.append(
            lambda event: print(
                "no ack from {} for allocation {}. Now is {}".format(
                    event.value[0],
                    event.value[1],
                    self.env.now)))
        p = self.schedule(
            action=
            lambda event: event.succeed(value=[agent_id, allocation['allocation_id']]),
            args={'event': noack_event},
            time=self.alloc_ack_timeout)
        self.timeouts[allocation['allocation_id']] = p
        self.schedule(
            self.comm.send, args={
                'request': packet,
                'remote': agent_id
            })

    def send_join_ack(self, dst):
        """ Acknowledge a network load has joing the network (added to known loads list)

        :param dst: destination of acknowledgemnt, should be the same load who requested joining.
        :returns:
        :rtype:

        """
        packet = {'msg_type': 'join_ack'}
        print("sending join ack")
        self.comm.send(packet, remote=dst)

    def stop(self):
        """ Stops the allocator, by first stop the AsyncComm interface then the parent Agent.

        :returns:
        :rtype:

        """
        packet = {'msg_type': 'stop'}
        for load in self.loads:
            self.schedule(
                self.comm.send, args={
                    'request': packet,
                    'remote': load
                })
        self.schedule(self.comm.stop)
        self.schedule(super(NetworkAllocator, self).stop)


class NetworkLoad(Agent):
    def __init__(self, remote='127.0.0.1:5555', local='*:5000', env=None):
        self.remote = remote
        self.local = local
        self.agent_id = self.local
        self.curr_allocation = 0
        self.comm = AsyncCommunication(identity=self.agent_id)
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        super(NetworkLoad, self).__init__(env=env)

    def receive_handle(self, data, src):
        """ Handled payload received from AsyncCommunication

        :param data: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        print("NetworkLoad handling {} from {}".format(data, src))
        msg_type = data['msg_type']
        if msg_type == 'join_ack':
            return
        if msg_type == 'allocation':
            allocation = data['allocation']
            print("allocation={}".format(allocation))
            self.schedule(
                action=self.send_ack,
                args={
                    'allocation': allocation,
                    'dst': src
                },
                time=0)
            print("handling allocation")
            self.schedule(
                action=self.allocation_handle,
                args={'allocation': allocation},
                time=1)
        if msg_type == 'stop':
            self.stop()

    def allocation_handle(self, allocation):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        duration = allocation['duration']
        value = allocation['allocation_value']
        print("Current load is {}".format(value))
        yield self.env.timeout(duration)

    def join_ack_handle(self):
        """ handle received join ack

        :returns:
        :rtype:

        """
        yield self.env.timeout(0)

    def send_join(self, dst):
        """ Send a join request to the allocator

        :param dst: destination address of the allocator
        :returns:
        :rtype:

        """
        packet = {
            'agent_id': self.agent_id,
            'msg_type': 'join',
            'allocation': self.curr_allocation
        }
        self.comm.send(packet, remote=dst)

    def send_ack(self, allocation, dst):
        """ Acknowledge a requested allocation to the Allocator.

        :param allocation: allocation that is processed
        :param dst: destination address of the Allocator
        :returns:
        :rtype:

        """
        packet = {
            'agent_id': self.agent_id,
            "msg_type": "allocation_ack",
            "allocation": allocation.copy()
        }
        self.comm.send(packet, remote=dst)

    def stop(self):
        """ Stop the NetworkLoad the the parent Agent.

        :returns:
        :rtype:

        """
        self.schedule(self.comm.stop)
        self.schedule(super(NetworkLoad, self).stop)
