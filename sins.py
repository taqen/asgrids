'''
TODO Handle allocation no_acknowledgemnt
TODO Handle proper network stop (stop packet + ack)
'''

from abc import abstractmethod
import hashlib
import simpy
import logging
from async_communication import AsyncCommunication
from defs import Allocation, Packet

logger = logging.getLogger('SINS')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)

   

# A generic Network Agent.
class Agent():
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        self.env = simpy.rt.RealtimeEnvironment(strict=True) if env is None else env
        self.timeouts = {}
        self.running = self.env.process(self._run())

    def run(self):
        logger.info("Agent - Started agent's infinite loop")
        try:
            self.env.run(until=self.running)
        except (KeyboardInterrupt, simpy.Interrupt):
            #if not self.running.processed:
            #    self.running.interrupt()
            self.stop()

    def _run(self):
        if isinstance(self.env, simpy.RealtimeEnvironment):
            self.env.sync()
        while True:
            try:
                yield self.env.timeout(1e-2)
            except simpy.Interrupt:
                logger.info("Agent - Agent._run interrupted")
                break

    def schedule(self, action, args=None, time=0, value=None):
        """ The agent's schedule function

        :param time: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :returns:
        :rtype:

        """
        logger.debug("Agent - scheduling action {}".format(action))
        return self.env.process(
            self.process(action=action, args=args, time=time, value=value))

    def process(self, action, args, time=0, value=None):
        try:
            value = yield self.env.timeout(time, value=value)
        except simpy.Interrupt:
            logger.debug("Agent - Interrupted action {}".format(action))
            return

        logger.debug("Agent - executing action {} after {} seconds".format(action, time))
        if args is None:
            action()
        else:
            action(**args)
        return value

    def stop(self):
        """ stop the Agent.
        Behavior left for child classes

        :returns:
        :rtype:

        """

        logger.debug("Agent - interrupting pending timeouts")
        for _,v in self.timeouts.items():
            if not v.processed and not v.triggered:
                v.interrupt()
        if len(self.timeouts) > 0:
            logger.info("Agent - remained {} timeouts not interrupted".format(len(self.timeouts)))
        self.running.interrupt()

    def create_timeout(self, timeout, event_id, msg=''):
        event = self.env.event()
        event.callbacks.append(
            lambda event: logger.info("Agent - timeout expired\n {}".format(msg)))
        event.callbacks.append(
            lambda event: self.cancel_timeout(event_id))
        event_process = self.schedule(
            action=lambda event: event.succeed(event_id),
            args={'event': event},
            time=timeout)
        return event_process

    def cancel_timeout(self, event_id):
        e = self.timeouts.pop(event_id, None)
        if e is None:
            raise ValueError("unknown event_id {}".format(event_id))
        if e is not None and not (e.processed or e.triggered):
            e.interrupt()


class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator

    def __init__(self, local='*:5555', env=None):
        self.local = local
        self.comm = AsyncCommunication(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.loads = {}
        self.alloc_ack_timeout = 2
        self.stop_ack_tiemout = 5
        logger.info("NetworkAllocator - Initializing NetworkAllocator {}".format(self.local))
        super(NetworkAllocator, self).__init__(env=env)

    def receive_handle(self, data, src):
        """ Handle packets received and decoded at the AsyncCommunication layer.

        :param data: received payload
        :param src: source of payload
        :returns:
        :rtype:

        """
        logger.debug("NetworkAllocator - handling {} from {}".format(data, src))
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
            event_id = hashlib.md5('allocation {} {}'.format(
                allocation['allocation_id'], src).encode()).hexdigest()
            logger.debug("NetworkAllocator - Cancelling event {}".format(event_id))
            self.cancel_timeout(event_id)
        elif msg_type == 'leave':
            agent_id = data['agent_id']
            self.remove_load(load_id=agent_id)
        if msg_type == 'stop':
            self.schedule(action=self.stop_network)
        if msg_type == 'stop_ack':
            event_id = hashlib.md5('stop {}'.format(src).encode()).hexdigest()
            self.cancel_timeout(event_id)
            self.remove_load(load_id=src)
        if msg_type == 'curr_allocation':
            agent_id = data['agent_id']
            allocation = data['allocation']
            self.add_load(load_id=agent_id, allocation=allocation)

    def add_load(self, load_id, allocation):
        """ Add a network load to Allocator's known loads list.

        :param load_id: id of load to be added (used as a dictionary key)
        :param allocation: the load's reported allocation when added.
        :returns:
        :rtype:

        """
        logger.info("NetworkAllocator - adding load {}".format(load_id))
        if load_id in self.loads:
            msg = "NetworkAllocator - load {} already added".format(load_id)
            if self.loads[load_id] == 0 or allocation['allocation_value'] != self.loads[load_id]['allocation_value']:
                msg = "{} - updated allocation from {} to {}".format(msg, self.loads[load_id], allocation)
                self.loads[load_id] = allocation
            logger.info(msg)
        else:
            self.loads[load_id] = allocation

    def remove_load(self, load_id):
        """ Remove a load from Allocator's known loads list.

        :param load_id: id (key) of load to be removed.
        :returns: The removed load.
        :rtype:

        """
        logger.info("NetworkAllocator - Removing load {}".format(load_id))
        return self.loads.pop(load_id, None)

    def send_allocation(self, agent_id, allocation):
        """ Send an allocation to a Network's load

        :param agent_id: id of destination load
        :param allocation: allocation to be sent
        :returns:
        :rtype:

        """
        logger.info("NetworkAllocator - sending allocation to {}".format(agent_id))
        packet = {'msg_type': 'allocation', 'allocation': allocation}

        # Creating Event that is triggered if no ack is received before a timeout
        event_id = hashlib.md5('allocation {} {}'.format(allocation['allocation_id'], agent_id).encode()).hexdigest()
        noack_event = self.create_timeout(
            event_id=event_id,
            timeout=self.alloc_ack_timeout,
            msg='NetworkAllocator - no ack from {} for allocation {}'.format(
                agent_id, allocation['allocation_id']))
        self.timeouts[event_id] = noack_event
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
        logger.info("NetworkAllocator - {} sending join ack to {}".format(self.local, dst))
        self.comm.send(packet, remote=dst)

    def stop_network(self):
        """ Stops the allocator.
        First, it stops all loads in self.loads.
        Second, wait self.stop_ack_timeout then stop parent Agent
        Third, stop self.comm
        :returns:
        :rtype:

        """
        packet = {'msg_type': 'stop'}
        logger.info("NetworkAllocator - Stopping these loads {}".format(self.loads))
        # Stopping register loads
        for load in self.loads:
            proc = self.schedule(
                self.comm.send, args={
                    'request': packet,
                    'remote': load
                }, value=load)
            proc.callbacks.append(lambda e: logger.info("NetworkAllocator - Sent stop to {}".format(e.value)))
            event_id = hashlib.md5('stop {}'.format(load).encode()).hexdigest()
            noack_event = self.create_timeout(
                timeout=self.stop_ack_tiemout,
                msg="NetworkAllocator - no stop_ack from {}".format(load),
                event_id=event_id)
            self.timeouts[event_id] = noack_event

        proc = self.schedule(self.stop, time=self.stop_ack_tiemout)
        # proc.callbacks.append(
        #     lambda event: map(lambda timeout: timeout.interrupt(), self.timeouts)
        # )
        #proc.callbacks.append(lambda event: self.running.interrupt())

    def stop(self):
        # Stop underlying simpy event loop
        super(NetworkAllocator, self).stop()
        # Inform AsyncCommThread we are stopping
        logger.info("NetworkAllocator - Stopping AsyncCommThread")
        self.comm.stop()
        # Wait for asyncio thread to cleanup properly
        self.comm.join()

class NetworkLoad(Agent):
    def __init__(self, remote='127.0.0.1:5555', local='*:5000', env=None):
        self.remote = remote
        self.local = local
        self.agent_id = self.local
        self.curr_allocation = 0
        self.comm = AsyncCommunication(callback=self.receive_handle,
                                       local_address=local,
                                       identity=self.agent_id)
        self.comm.start()
        logger.info("NetworkLoad {} - Initializing".format(self.local))

        super(NetworkLoad, self).__init__(env=env)

    def receive_handle(self, data, src):
        """ Handled payload received from AsyncCommunication

        :param data: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        logger.info("NetworkLoad {} - handling {} from {}".format(self.agent_id, data, src))
        msg_type = data['msg_type']
        if msg_type == 'join_ack':
            logger.info("NetworkLoad {} - Joined successfully allocator {}".format(self.agent_id, src))
        if msg_type == 'allocation':
            allocation = data['allocation']
            logger.debug("allocation={}".format(allocation))
            self.schedule(
                action=self.send_ack,
                args={
                    'allocation': allocation,
                    'dst': src
                })
            self.schedule(
                action=self.allocation_handle,
                args={'allocation': allocation})
        if msg_type == 'stop':
            self.schedule(action=lambda: self.comm.send(
                {'msg_type':'stop_ack'}, remote=src
            ))
            # Too much events at same time breaks realtime
            proc = self.schedule(action=self.stop, time=1)
            proc.callbacks.append(lambda e: self.running.interrupt())

    def allocation_handle(self, allocation):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        logger.info(
            "NetworkLoad {} - Current load is {}".format(
            self.agent_id,
            self.curr_allocation['allocation_value'])
            )

        self.curr_allocation = allocation.copy()

        logger.info(
            "NetworkLoad {} - Updated load is {}".format(
            self.agent_id,
            allocation['allocation_value'])
            )
        #yield self.env.timeout(0)
        #yield self.env.timeout(allocation['duration'])

    def allocation_report(self):
        packet = {
            'agent_id':self.agent_id,
            'msg_type':'curr_allocation',
            'allocation':self.curr_allocation
            }
        logger.info("NetworkLoad {} - Reporting allocation {} to {}".format(
            self.agent_id, self.curr_allocation, self.remote))
        self.schedule(self.comm.send, args={'request':packet, 'remote':self.remote})

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
        self.schedule(self.comm.send, args={"request":packet, "remote":dst})

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
        self.schedule(self.comm.send, args={"request":packet, "remote":dst})

    def send_leave(self, dst):
        logger.info("NetworkLoad {} - Leaving {}".format(self.agent_id, dst))
        packet = {
            'agent_id': self.agent_id,
            'msg_type': 'leave'
        }
        self.schedule(self.comm.send, args={"request":packet, "remote":dst})
    def stop(self):
        # Stop underlying simpy event loop
        super(NetworkLoad, self).stop()
        # Inform AsyncCommThread we are stopping
        self.comm.stop()
        # Wait for asyncio thread to cleanup properly
        self.comm.join()
