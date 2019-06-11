#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .agent import Agent
from .defs import EventId, Packet, Allocation
from simpy.exceptions import Interrupt
from itertools import count

class NetworkAllocator(Agent):
    # Simulate a communicating policy allocator
    def __init__(self, local=None, env=None):
        super(NetworkAllocator, self).__init__(env=env)
        self.nid = local
        self.nodes = {}
        self.alloc_ack_timeout = 3
        self.stop_ack_timeout = 5
        self.local = local
        self.identity = self.nid
        self.type = "NetworkAllocator"
        self.alloc_timeouts = {}
        self.stop_timeouts = {}
        self.aid_count = count()
        # various callbacks
        self.allocation_updated = None

    def receive_handle(self, p: Packet, src=None):
        """ Handle packets received and decoded at the AsyncCommunication layer.

        :param data: received payload
        :param src: source of payload
        :returns:
        :rtype:
        """
        assert isinstance(p, Packet)
        if src is None:
            src = p.src

        self.logger.info("handling {} from {}".format(p, src))
        msg_type = p.ptype
        if msg_type == 'join':
            self.add_node(nid=p.src, allocation=p.payload)
            self.schedule(self.send_join_ack, {'dst': p.src})
        elif msg_type == 'allocation_ack':
            self.logger.info("received allocation_ack from {} for allocation {}".format(p.src, p.payload[0].aid))
            # self.add_node(nid=p.src, allocation=p.payload)
            # Interrupting ack timeout event for this allocation
            # try:
            #     aid = p.payload[0].aid
            #     if aid not in self.alloc_timeouts:
            #         self.logger.warning("received ack, but didn't send an allocation: {}".format(aid))
            #     elif self.alloc_timeouts[aid] is not None:
            #         self.logger.debug("canceling ack timeout for allocation: {}".format(aid))
            #         self.interrupt_event(self.alloc_timeouts.pop(aid))
            #     else:
            #         self.logger.warning("received duplicate allocation_ack from {}!!!".format(p.src))
            # except Exception as e:
            #     self.logger.warning("exception while canceling alloc_timeouts: {}".format(e))
        elif msg_type == 'leave':
            self.schedule(self.remove_node, {'nid': p.src})
        elif msg_type == 'stop':
            self.schedule(self.stop_network)
        elif msg_type == 'stop_ack':
            self.logger.debug("Received stop_ack from {}".format(p.src))
            # Interrupting ack timeout event for this allocation
            try:
                self.interrupt_event(self.stop_timeouts[p.src])
            except Exception as e:
                self.logger.warning(e)
            self.remove_node(nid=src)
        elif msg_type == 'curr_allocation':
            self.add_node(nid=p.src, allocation=p.payload)

    def add_node(self, nid, allocation):
        """ Add a network node to Allocator's known nodes list.

        :param nid: id of node to be added (used as a dictionary key)
        :param allocation: the node's reported allocation when added.
        :returns:
        :rtype:

        """
        self.logger.info("adding node {}".format(nid))
        if nid in self.nodes:
            msg = "node {} already added".format(nid)
            if allocation[0] != self.nodes[nid][0] or allocation[1] != self.nodes[nid][1]:
                msg = "{} - updated allocation from {} to {}".format(msg, self.nodes[nid], allocation)
                if callable(self.allocation_updated):
                    try:
                        self.allocation_updated(allocation, nid)
                    except Exception as e:
                        self.logger.warning("Failed calling allocation_updated({}, {}".format(allocation, nid))

                self.nodes[nid] = allocation

            self.logger.info(msg)
        else:
            self.nodes[nid] = allocation

    def remove_node(self, nid):
        """ Remove a node from Allocator's known nodes list.

        :param nid: id (key) of node to be removed.
        :returns: The removed node.
        :rtype:

        """
        self.logger.info("Removing node {}".format(nid))
        return self.nodes.pop(nid, None)

    def send_allocation(self, nid, allocation):
        """ Send an allocation to a Network's node

        :param nid: id of destination node
        :param allocation: allocation to be sent
        :returns:
        :rtype:

        """
        a = Allocation(next(self.aid_count), allocation.p_value, allocation.q_value, allocation.duration)
        self.logger.info("sending allocation {} to {}".format(a.aid, nid))
        packet = Packet(ptype='allocation', payload=a, src=self.local, dst=nid)

        # Creating Event that is triggered if no ack is received before a timeout
        # msg='no ack from {} for allocation {}'.format(nid, a.aid)
        # try:
        #     self.alloc_timeouts[a.aid] = self.schedule(
        #         lambda msg: self.logger.warning(msg),
        #         [msg],
        #         delay=self.alloc_ack_timeout,
        #         callbacks=[lambda aid=a.aid: self.alloc_timeouts.pop(aid)])
        # except Exception as e:
        #     self.logger.warning(e)
        self.send(packet, remote=nid)

    def send_join_ack(self, dst):
        """ Acknowledge a network node has joining the network (added to known nodes list)

        :param dst: destination of acknowledgement, should be the same node who requested joining.
        :returns:
        :rtype:

        """
        packet = Packet('join_ack', src=self.local, dst=dst)
        self.logger.info("{} sending join ack to {}".format(self.local, dst))
        self.send(packet, remote=dst)

    def stop_network(self):
        """ Stops the allocator.
        First, it stops all nodes in self.nodes.
        Second, wait self.stop_ack_timeout then stop parent Agent
        Third, stop self.comm
        :returns:
        :rtype:

        """
        # Stopping register nodes
        for node in list(self.nodes):
            packet = Packet(ptype='stop', src=self.local, dst=node)
            self.send(packet, remote=node)
            self.logger.info("Sent stop to {}".format(node))
            eid = EventId(packet, node)
            event = self.create_timeout(timeout=self.stop_ack_timeout, msg="no stop_ack from {}".format(node), eid=eid)
            self.stop_timeouts[node] = event
            self.logger.info("Stopping {}".format(node))

        while True:
            if len(self.nodes) == 0:
                self.logger.info("All nodes stopped")
                break
        self.stop()

    def stop(self):
        """ Stops the NetworkAllocator Node and associated AsyncCommunication
        """

        # Stop underlying simpy event loop
        self.logger.info("Stopping Simpy")
        super(NetworkAllocator, self).stop()
