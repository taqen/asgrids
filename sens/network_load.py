#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Callable
from simpy.exceptions import Interrupt

from .agent import Agent
from .defs import Allocation, Packet


class NetworkLoad(Agent):
    def __init__(self, local=None, remote=None, env=None):
        super(NetworkLoad, self).__init__(env=env)
        self.remote = remote
        self.nid = self.local
        self.curr_allocation: Allocation = Allocation()
        self.local: str = local
        self.callback: Callable = self.handle_receive
        self.identity: str = self.nid
        self.type: str = "NetworkLoad"
        # storage for current electrical measures
        self.curr_measure: float = 0
        # callback to call when reporting allocation, to get current electrical measures.
        self.update_measure: Callable = None
        # callback to call when node received join_ack
        self.joined_callback: Callable = None
        # callback to generate allocation values for this NetworkLoad
        self.generate_allocations: Callable = None
        # Event that will trigger handle_allocation for next value
        self.next_allocation = None
        self.join_ack_timeout = 3
        self.join_ack_timer = None

    def handle_receive(self, p, src=None):
        """ Handled payload received from AsyncCommunication

        :param p: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p

        self.logger.info("handling {} from {}".format(p, p.src))
        msg_type = p.ptype

        if msg_type == 'join_ack':
            self.logger.info("Joined successfully allocator {}".format(p.src))
            self.remote = p.src
            self.join_ack_timer.fail(BaseException("Interrupted"))
            if self.joined_callback is not None:
                self.joined_callback(self.local, self.remote)

        if msg_type == 'allocation':
            # Interrupting any pending next allocation
            # because allocator demands take priority
            if self.next_allocation is not None:
                self.next_allocation.fail(BaseException("Interrupted"))
                self.next_allocation = None

            if isinstance(p.payload, Allocation):
                allocation = p.payload
            elif isinstance(p.payload, list) and isinstance(p.payload[0], Allocation):
                allocation = p.payload[0]
            else:
                raise ValueError

            self.logger.info("received allocation={}".format(allocation))
            self.schedule(action=self.send_ack,
                          args={'allocation': [allocation, self.curr_measure], 'dst': p.src})
            self.schedule(action=self.handle_allocation, args={'allocation': allocation, 'report': False})

        if msg_type == 'stop':
            self.logger.info("Received Stop from {}".format(p.src))
            self.send(Packet(ptype='stop_ack', src=self.local), p.src)
            self.schedule(self.stop)

    def handle_allocation(self, allocation, report=True):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        self.logger.info("{} - Current allocation value is {}".format(self.local, self.curr_allocation))

        self.curr_allocation = allocation

        self.logger.info("{} - New allocation value is {}".format(self.local, self.curr_allocation))

        if self.update_measure is not None:
            try:
                measure = self.update_measure(self.curr_allocation, self.local)
            except Exception as e:
                self.logger.info("Couldn't update measure: {}".format(e))
            if measure is not None:
                self.curr_measure = measure
                self.logger.info("New measure is {}v".format(measure))

        if report:
            self.schedule(self.report_allocation)

        if self.generate_allocations is not None:
            self.logger.info("Scheduling allocation generation")
            self.next_allocation = self.schedule(
                self.handle_allocation,
                {'allocation': self.generate_allocations(self.local, self.curr_allocation)},
                delay=self.curr_allocation.duration)

    def report_allocation(self):
        if self.remote is not None:
            self.logger.info("Reporting allocation {} to {}".format(self.curr_allocation, self.remote))
            packet = Packet('curr_allocation', [self.curr_allocation, self.curr_measure], self.local)
            self.send(packet, self.remote)
        else:
            self.logger.info("Not reporting, remote not defined yet")

    def send_join(self, dst):
        """ Send a join request to the allocator

        :param dst: destination address of the allocator
        :returns:
        :rtype:

        """
        try:
            self.logger.info('{} Joining {}'.format(self.local, dst))
            packet = Packet('join', [self.curr_allocation, None], self.local)
            self.join_ack_timer = self.create_timeout(
                    timeout=self.join_ack_timeout, eid=0,
                    msg='no join ack from {}'.format(dst))
            self.join_ack_timer.callbacks.append(lambda e: self.send_join(dst))
            self.send(packet, dst)
        except Exception as e:
            self.logger.warning("Error sending join: {}".format(e))

    def send_ack(self, allocation, dst):
        """ Acknowledge a requested allocation to the Allocator.

        :param allocation: allocation that is processed
        :param dst: destination address of the Allocator
        :returns:
        :rtype:

        """
        self.logger.info("{} sending allocation_ack to {}".format(self.local, dst))
        packet = Packet('allocation_ack', allocation, self.local)

        self.send(packet, dst)

    def send_leave(self, dst):
        self.logger.info("Leaving {}".format(dst))

        packet = Packet(ptype='leave', src=self.local)

        self.send(packet, dst)

    def stop(self):
        # Stop underlying simpy event loop
        self.logger.info("Stopping Simpy")
        self.remote = None
        super(NetworkLoad, self).stop()
