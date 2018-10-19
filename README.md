
# Table of Contents

1.  [Preliminary Architecture](#org023c124)
    1.  [The Generic Agent](#orgc72bd4a)
    2.  [The Allocator Agent](#orgccb2621)
    3.  [The Network Load Agent](#org750e490)

<a id="org023c124"></a>

# Preliminary Architecture

In order to model the operation of a smart grid, the simulator needs to operates asynchronously on a distributed architecture.
As a consequence a multi-agent design paradigm is probably a good way to describe it.


<a id="orgc72bd4a"></a>

## The Generic Agent

The generic agent translates to the basic class the implements the basic behavior of running an endless event loop, and processing actions as they are scheduled.
The Agent interacts with the outside world through AsyncComms interface. This interface is implmented through various child classes the inherit from the Agent.
The interaction between the scheduling and AsyncComms interface is as can be seen in <a id="orgca9be06"></a>.
The code block bellow shows an implementation of such an Agent.

    class Agent:
      """ A generic Network Agent.
      """
      def __init__(self, env=None):
        if env is None:
          self.env = simpy.Environment()
        else:
          self.env = env
        self.stop = False
        self.env.process(self.run())
        self.env.run()
    
      def run(self):
        while not self.stop:
          #self.env.process(self.run)
          yield self.env.timeout(10)
    
      def schedule(self, time, action):
        """ generates a production/consumption event
        """
        p = self.env.process(action, delay=time)
        return p
    
      def stop(self):
        self.stop = True


<a id="orgccb2621"></a>

## The Allocator Agent

Contains the standard facilities of Scheduling and Communicating, wrapped around simpy and AsyncCommunication.
The allocator doesn't consume or produce per se, but generates production and consumption profiles corresponding for network elements (generators, loads &#x2026; etc).
The class definition is bellow

    class NetworkAllocator(Agent):
      """ Simulate a communicating policy allocator
      """
      def __init__(self, local='*:5555'):
        self.loads = {}
        self.comm = AsyncCommunication()
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.local = local
        super(NetworkAllocator, self).__init__()
    
      def initlise(self):
        pass
    
      def receive_handle(self, data, src):
        pass
      def add_load(self, load):
        self.loads[load['id']] = load
    
      def remove_load(self, id):
        self.loads.popitem(id)
    
      def send_allocation(self, id , allocation):
        self.schedule(action = send_allocation(id, allocation))
    
      def stop(self):
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkAllocator, self).stop())


<a id="org750e490"></a>

## The Network Load Agent

The Network Load models the behavior of an Agent that can handle Allocator commands to consume/produce specific allocations.
It inherits from the Generic Agents and interfaces with the outside world through the AsyncCommunication class.

    class NetworkLoad(Agent):
      def __init__(self, remote='127.0.0.1:5555', local='*:5000'):
        self.remote = remote
        self.local = local
        self.id=self.local
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
          duration = data['duration']
          self.schedule(time=0, action=send_ack(allocation, dst=src))
          self.schedule(time=0, action=allocation_handle(allocation, duration))
    
      def allocation_handle(self, allocation, duration):
        yield self.env.timeout(duration)
    
      def join_ack_handle(self):
        pass
    
      def send_join(self):
        packet={'msg_type':'join', 'id':self.id}
      def send_ack(self, allocation):
        packet={"allocation_id" : allocation['allocation_id'], "msg_type": "allocation_ack"}
        self.comm.send(packet, remote=self.remote)
    
      def stop(self):
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkLoad, self).stop())
