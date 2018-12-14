from .defs import Packet, Allocation, EventId
from .agent import Agent
from .async_communication import AsyncCommunication
import logging

class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator
    def __init__(self, local=None, env=None):
        super(NetworkAllocator, self).__init__(env=env)
        self.nid = local
        self.nodes = {}
        self.alloc_ack_timeout = 2
        self.stop_ack_timeout = 5
        self.local = local
        self.callback = self.receive_handle
        self.identity = self.nid

        loggername = 'Agent.NetworkAllocator.{}'.format(self.local)
        self.__logger = logging.getLogger(loggername)
        self.__logger.info("Initializing NetworkAllocator")

    def receive_handle(self, p: Packet, src=None):
        """ Handle packets received and decoded at the AsyncCommunication layer.

        :param data: received payload
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p
        src = src
        if src is None:
            src = p.src

        self.__logger.info("handling {} from {}".format(p, src))
        msg_type = p.ptype
        if msg_type == 'join':
            self.add_node(nid=p.src, allocation=p.payload)
            self.schedule(self.send_join_ack, {'dst': p.src})
        elif msg_type == 'allocation_ack':
            self.add_node(nid=p.src, allocation=p.payload)
            # Interrupting timeout event for this allocation
            eid = EventId(p)
            self.schedule(self.remove_timeout, {'eid':eid})
        elif msg_type == 'leave':
            self.schedule(self.remove_node, {'nid':p.src})
        if msg_type == 'stop':
            self.schedule(self.stop_network)
        if msg_type == 'stop_ack':
            self.__logger.debug("Received stop_ack from {}".format(p.src))
            eid = EventId(p)
            try:
                self.remove_timeout(eid)
            except Exception as e:
                ValueError(e)
            self.remove_node(nid=src)
        if msg_type == 'curr_allocation':
            self.add_node(nid=p.src, allocation=p.payload)

    def add_node(self, nid, allocation):
        """ Add a network node to Allocator's known nodes list.

        :param nid: id of node to be added (used as a dictionary key)
        :param allocation: the node's reported allocation when added.
        :returns:
        :rtype:

        """
        self.__logger.info("adding node {}".format(nid))
        if nid in self.nodes:
            msg = "node {} already added".format(nid)
            if allocation != self.nodes[nid]:
                msg = "{} - updated allocation from {} to {}".format(msg, self.nodes[nid], allocation)
                self.nodes[nid] = allocation
            self.__logger.info(msg)
        else:
            self.nodes[nid] = allocation

    def remove_node(self, nid):
        """ Remove a node from Allocator's known nodes list.

        :param nid: id (key) of node to be removed.
        :returns: The removed node.
        :rtype:

        """
        self.__logger.info("Removing node {}".format(nid))
        return self.nodes.pop(nid, None)

    def send_allocation(self, nid, allocation):
        """ Send an allocation to a Network's node

        :paramnid: id of destination node
        :param allocation: allocation to be sent
        :returns:
        :rtype:

        """
        self.__logger.info("sending allocation to {}".format(nid))
        packet = Packet('allocation', allocation)

        # Creating Event that is triggered if no ack is received before a timeout
        eid = EventId(allocation, nid)
        self.create_timer(
            eid=eid,
            timeout=self.alloc_ack_timeout,
            msg='no ack from {} for allocation {}'.format(
               nid, allocation.aid))
        self.comm.send(packet, nid)

    def send_join_ack(self, dst):
        """ Acknowledge a network node has joing the network (added to known nodes list)

        :param dst: destination of acknowledgemnt, should be the same node who requested joining.
        :returns:
        :rtype:

        """
        packet = Packet('join_ack')
        self.__logger.info("{} sending join ack to {}".format(self.local, dst))
        self.comm.send(packet, remote=dst)

    def stop_network(self):
        """ Stops the allocator.
        First, it stops all nodes in self.nodes.
        Second, wait self.stop_ack_timeout then stop parent Agent
        Third, stop self.comm
        :returns:
        :rtype:

        """
        packet = Packet(ptype='stop', src=self.local)
        # Stopping register nodes
        for node in list(self.nodes):
            self.comm.send(request=packet, remote=node)
            self.__logger.info("Sent stop to {}".format(node))
            eid = EventId(packet, node)
            self.create_timer(
                timeout=self.stop_ack_timeout,
                msg="no stop_ack from {}".format(node),
                eid=eid)
            self.__logger.info("Stopping {}".format(node))

        while True:
            if len(self.nodes) == 0:
                self.__logger.info("All nodes stopped")
                break
        self.stop()

    def stop(self):
        # Stop underlying simpy event loop
        self.__logger.info("Stopping Simpy")
        super(NetworkAllocator, self).stop()