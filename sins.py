'''
TODO Handle allocation no_acknowledgemnt
TODO Handle proper network stop (stop packet + ack)
'''

from abc import abstractmethod
import hashlib
import simpy
import logging
from async_communication import AsyncCommunication
from defs import Allocation, Packet, EventId

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
        if isinstance(self.env, simpy.RealtimeEnvironment):
            self.env.sync()
        try:
            self.env.run(until=self.running)
        except (KeyboardInterrupt, simpy.Interrupt) as e:
            #if not self.running.processed:
            #    self.running.interrupt()
            logger.debug("Agent - {}".format(e))
            self.stop()

    def _run(self):
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

    def create_timer(self, timeout, eid, msg=''):
        logger.debug("Agent - Creating timer {}".format(eid))
        event = self.env.event()
        event.callbacks.append(
            lambda event: logger.info("Agent - timeout expired\n {}".format(msg)))
        event.callbacks.append(
            lambda event: self.cancel_timer(eid))
        event_process = self.schedule(
            action=lambda event: event.succeed(eid),
            args={'event': event},
            time=timeout)
        return event_process

    def cancel_timer(self, eid):
        logger.debug("Agent - canceling timer {}".format(eid))
        e = self.timeouts.pop(eid, None)
        if e is None:
            logger.info("No eid %s"%eid)
        if e is not None and not (e.processed or e.triggered):
            e.interrupt()

class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator

    def __init__(self, local='127.0.0.1:5555', env=None):
        self.local = local
        self.nid = local
        self.comm = AsyncCommunication(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.nodes = {}
        self.alloc_ack_timeout = 2
        self.stop_ack_tiemout = 5
        logger.info("Initializing NetworkAllocator {}".format(self.local))
        super(NetworkAllocator, self).__init__(env=env)

    def receive_handle(self, p: Packet, src):
        """ Handle packets received and decoded at the AsyncCommunication layer.

        :param data: received payload
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p

        logger.info("handling {} from {}".format(p, src))
        msg_type = p.ptype
        if msg_type == 'join':
            self.add_node(nid=p.src, allocation=p.payload)
            self.schedule(action=self.send_join_ack, args={'dst': p.src})
        elif msg_type == 'allocation_ack':
            self.add_node(nid=p.src, allocation=p.payload)
            # Interrupting timeout event for this allocation
            eid = EventId(p)
            logger.debug("Cancelling event {}".format(eid))
            self.cancel_timer(eid)
        elif msg_type == 'leave':
            self.remove_load(nid=p.src)
        if msg_type == 'stop':
            self.schedule(action=self.stop_network)
        if msg_type == 'stop_ack':
            logger.debug("Received stop_ack from {}".format(p.src))
            eid = EventId(p)
            try:
                self.cancel_timer(eid)
            except Exception as e:
                ValueError(e)
            self.remove_load(nid=src)
        if msg_type == 'curr_allocation':
            self.add_node(nid=p.src, allocation=p.payload)

    def add_node(self, nid, allocation):
        """ Add a network node to Allocator's known nodes list.

        :param nid: id of node to be added (used as a dictionary key)
        :param allocation: the node's reported allocation when added.
        :returns:
        :rtype:

        """
        logger.info("adding node {}".format(nid))
        if nid in self.nodes:
            msg = "node {} already added".format(nid)
            if self.nodes[nid] == 0 or allocation.value != self.nodes[nid].value:
                msg = "{} - updated allocation from {} to {}".format(msg, self.nodes[nid], allocation)
                self.nodes[nid] = allocation
            logger.info(msg)
        else:
            self.nodes[nid] = allocation

    def remove_load(self, nid):
        """ Remove a node from Allocator's known nodes list.

        :param nid: id (key) of node to be removed.
        :returns: The removed node.
        :rtype:

        """
        logger.info("Removing node {}".format(nid))
        return self.nodes.pop(nid, None)

    def send_allocation(self, nid, allocation):
        """ Send an allocation to a Network's node

        :paramnid: id of destination node
        :param allocation: allocation to be sent
        :returns:
        :rtype:

        """
        logger.info("sending allocation to {}".format(nid))
        packet = Packet('allocation', allocation)

        # Creating Event that is triggered if no ack is received before a timeout
        eid = EventId(allocation, nid)
        noack_event = self.create_timer(
            eid=eid,
            timeout=self.alloc_ack_timeout,
            msg='no ack from {} for allocation {}'.format(
               nid, allocation.aid))
        self.timeouts[eid] = noack_event
        self.comm.send(packet, nid)

    def send_join_ack(self, dst):
        """ Acknowledge a network node has joing the network (added to known nodes list)

        :param dst: destination of acknowledgemnt, should be the same node who requested joining.
        :returns:
        :rtype:

        """
        packet = Packet('join_ack')
        logger.info("{} sending join ack to {}".format(self.local, dst))
        self.comm.send(packet, remote=dst)

    def stop_network(self):
        """ Stops the allocator.
        First, it stops all nodes in self.nodes.
        Second, wait self.stop_ack_timeout then stop parent Agent
        Third, stop self.comm
        :returns:
        :rtype:

        """
        packet = Packet(ptype='stop', src=self.nid)
        # Stopping register nodes
        for node in self.nodes:
            proc = self.schedule(
                self.comm.send, args={
                    'request': packet,
                    'remote': node
                }, value=node)
            proc.callbacks.append(lambda e: logger.info("Sent stop to {}".format(e.value)))
            eid = EventId(packet, node)
            noack_event = self.create_timer(
                timeout=self.stop_ack_tiemout,
                msg="no stop_ack from {}".format(node),
                eid=eid)
            self.timeouts[eid] = noack_event
            logger.info("Stopping {}".format(node))

        proc = self.schedule(self.stop, time=self.stop_ack_tiemout)

    def stop(self):
        # Stop underlying simpy event loop
        logger.info("Stopping Simpy")
        super(NetworkAllocator, self).stop()
        # Inform AsyncCommThread we are stopping
        logger.info("Stopping AsyncCommThread")
        self.comm.stop()
        # Wait for asyncio thread to cleanup properly
        self.comm.join()

class NetworkLoad(Agent):
    def __init__(self, remote='127.0.0.1:5555', local='127.0.0.1:5000', env=None):
        fh = logging.FileHandler('network_load_{}.log'.format(local.split(':')[1]))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        self.remote = remote
        self.local = local
        self.nid = self.local
        self.curr_allocation = Allocation()
        self.comm = AsyncCommunication(callback=self.receive_handle,
                                       local_address=local,
                                       identity=self.nid)
        self.comm.start()
        logger.info("{} - Initializing".format(self.local))

        super(NetworkLoad, self).__init__(env=env)

    def receive_handle(self, data, src):
        """ Handled payload received from AsyncCommunication

        :param data: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        logger.info("{} - handling {} from {}".format(self.nid, data, src))
        msg_type = data.ptype
        if msg_type == 'join_ack':
            logger.info("{} - Joined successfully allocator {}".format(self.nid, src))
        if msg_type == 'allocation':
            allocation = data.payload
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
            logger.info("{} - Received Stop from {}".format(self.nid, src))
            proc = self.schedule(self.comm.send, 
                args={
                    'request':Packet(ptype='stop_ack', src=self.nid),
                    'remote':src}
            )
            #proc.callbacks.append(self.stop)
            # Too much events at same time breaks realtime
            self.schedule(action=self.stop, time=1)

    def allocation_handle(self, allocation):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        logger.info(
            "{} - Current node is {}".format(
            self.nid,
            self.curr_allocation['allocation_value'])
            )

        self.curr_allocation = allocation

        logger.info(
            "{} - Updated node is {}".format(
            self.nid,
            allocation['allocation_value'])
            )
        #yield self.env.timeout(0)
        #yield self.env.timeout(allocation.duration)

    def allocation_report(self):
        packet = Packet('curr_allocation', self.curr_allocation, self.nid)

        logger.info("{} - Reporting allocation {} to {}".format(
            self.nid, self.curr_allocation, self.remote))

        self.comm.send(packet, self.remote)

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
        logger.info('{} - Joining {}'.format(self.nid, dst))
        packet = Packet('join', self.curr_allocation, self.nid)
        self.comm.send(packet, dst)

    def send_ack(self, allocation, dst):
        """ Acknowledge a requested allocation to the Allocator.

        :param allocation: allocation that is processed
        :param dst: destination address of the Allocator
        :returns:
        :rtype:

        """
        packet = Packet('allocation_ack', allocation, self.nid)

        self.comm.send(packet, dst)

    def send_leave(self, dst):
        logger.info("{} - Leaving {}".format(self.nid, dst))
    
        packet = Packet(ptype='leave', src=self.nid)

        self.comm.send(packet, dst)

    def stop(self):
        # Stop underlying simpy event loop
        super(NetworkLoad, self).stop()
        # Inform AsyncCommThread we are stopping
        self.comm.stop()
        # Wait for asyncio thread to cleanup properly
        self.comm.join()
