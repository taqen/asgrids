import simpy
from async_communication import AsyncCommunication

# A generic Network Agent.
class Agent:
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        if env is None:
            self.env = simpy.Environment()
        else:
            self.env = env
        self.running = True
        self.env.process(self.run())
        self.env.run()

    def run(self):
        """ Starting the local simulation event loop
        To avoid executing run every time an event is scheduled,
        an empty event is infinitely scheduled
        """
        while self.running:
            yield self.env.timeout(1)

    def schedule(self, time, action):
        """ The agent's schedule function

        :param time: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :returns: 
        :rtype: 

        """
        p = self.env.process(action, delay=time)
        return p

    def stop(self):
        """ stop the Agent by stop the local simpy environment.

        :returns: 
        :rtype: 

        """
        self.running = False

class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator

    def __init__(self, local='*:5555'):
        self.local = local
        self.comm = AsyncCommunication()
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.loads = {}
        super(NetworkAllocator, self).__init__()

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
            self.schedule(time=0, action=self.send_join_ack(dst=src))
        elif msg_type == 'allocation_ack':
            agent_id = data['agent_id']
            allocation = data['allocation']
            self.add_load(load_id=agent_id, allocation=allocation)
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
        packet = {'msg_type': 'allocation', 'allocation': allocation}
        self.schedule(action=self.comm.send(agent_id, packet))

    def send_join_ack(self, dst):
        """ Acknowledge a network load has joing the network (added to known loads list)

        :param dst: destination of acknowledgemnt, should be the same load who requested joining.
        :returns: 
        :rtype: 

        """
        packet = {'msg_type': 'join_ack'}
        self.schedule(action=self.comm.send(packet, remote=dst))

    def stop(self):
        """ Stops the allocator, by first stop the AsyncComm interface then the parent Agent.

        :returns: 
        :rtype: 

        """
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkAllocator, self).stop())

class NetworkLoad(Agent):
    def __init__(self, remote='127.0.0.1:5555', local='*:5000'):
        self.remote = remote
        self.local = local
        self.agent_id = self.local
        self.curr_allocation = 0
        self.comm = AsyncCommunication(identity=self.id)
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        super(NetworkLoad, self).__init__()

    def receive_handle(self, data, src):
        msg_type = data['msg_type']
        if msg_type == 'ack':
            return
        if msg_type == 'allocation':
            allocation = data['allocation']
            self.schedule(time=0, action=self.send_ack(allocation, dst=src))
            self.schedule(time=0, action=self.allocation_handle(allocation))

    def allocation_handle(self, allocation):
        duration = allocation['duration']
        value = allocation['allocation_value']
        print("Current load is {}".format(value))
        yield self.env.timeout(duration)

    def join_ack_handle(self):
        pass

    def send_join(self, dst):
        packet = {
            'agent_id': self.agent_id,
            'msg_type': 'join',
            'allocation': self.curr_allocation
        }
        self.schedule(time=0, action=self.comm.send(packet, remote=dst))

    def send_ack(self, allocation, dst):
        packet = {
            'agent_id': self.agent_id,
            "msg_type": "allocation_ack",
            "allocation": allocation.copy()
        }
        self.schedule(time=0, action=self.comm.send(packet, remote=dst))

    def stop(self):
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkLoad, self).stop())
