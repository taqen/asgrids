#!/usr/bin/env python
# -*- coding: utf-8 -*-

from typing import Callable
from simpy.exceptions import Interrupt
from time import monotonic as time

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
        self.update_measure_cb: Callable = None
        self.update_measure_period = 2
        # callback to call when node received join_ack
        self.joined_callback: Callable = None
        # callback to generate allocation values for this NetworkLoad
        self.generate_allocations: Callable = None
        self.generate_allocations_period = 2
        # Event that will trigger handle_allocation for next value
        self.next_allocation = None
        self.join_ack_timeout = 3
        self.join_ack_timer = None

        self.max_allocation = Allocation(p_value=float("inf"), q_value=float("inf"))

    def run(self):
        super(NetworkLoad, self).run()
        try:
            self.schedule(self.get_allocation, delay=self.generate_allocations_period)
            self.schedule(self.update_measure, delay=self.update_measure_period)
        except Exception as e:
            self.logger.warning(e)


    def handle_receive(self, p, src=None):
        """ Handled payload received from AsyncCommunication

        :param p: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p
        self.logger.info("handling {} from {}".format(p, p.src))
        if p.dst != self.local:
            self.logger.warning("packet not not for {}; for {}".format(self.local, p.dst))
            return

        msg_type = p.ptype

        if msg_type == 'join_ack':
            self.logger.info("Joined successfully allocator {}".format(p.src))
            self.remote = p.src
            self.interrupt_event(self.join_ack_timer)
            if self.joined_callback is not None:
                self.joined_callback(self.local, self.remote)
        elif msg_type == 'allocation':
            allocation = None
            if isinstance(p.payload, Allocation):
                allocation = p.payload
            elif isinstance(p.payload, list) and isinstance(p.payload[0], Allocation):
                allocation = p.payload[0]
            else:
                self.logger.warning("unsupported instance for packet Payload: {}".format(type(p.payload)))
                raise ValueError

            self.logger.info("received allocation={}".format(allocation))
            self.send_ack([allocation, self.curr_measure], p.src)
            self.schedule(self.handle_allocation, args=[allocation])
        elif msg_type == 'stop':
            self.logger.info("Received Stop from {}".format(p.src))
            self.send(Packet(ptype='stop_ack', src=self.local), p.src)
            self.schedule(self.stop)

    def handle_allocation(self, allocation):
        """ Handle a received allocation
        This will also trigger update_measure (if available) to get updated voltage value.
        It will also schedule 

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        # Allocation is interpreted as a quota to be enforced
        self.logger.debug("{} - Current allocation value is {}".format(self.local, self.curr_allocation))
        if abs(allocation.p_value) <= abs(self.max_allocation.p_value):
            self.curr_allocation = allocation
            if self.next_allocation is not None:
                self.interrupt_event(self.next_allocation)
                self.next_allocation = self.schedule(self.get_allocation, delay=self.curr_allocation.duration)
            self.logger.info("{} - New allocation value is {}".format(self.local, self.curr_allocation))
        else:
            self.logger.info("Can't execute allocation: {}. Beyond node's ability {}".format(allocation, self.max_allocation))

    def get_allocation(self):
        """ Tries to query and allocations source for a new allocation to execute
        The new allocation will also be saved as limit for eventual orders received from an allocator
        """
        if self.generate_allocations is not None:
            self.logger.info("Scheduling allocation generation")
            self.max_allocation = self.generate_allocations(self.local, self.curr_allocation, self.env.now)
            self.schedule(self.handle_allocation, args={'allocation': self.max_allocation})
        else:
            self.logger.info("No source defined to generate allocations")

        if self.max_allocation is not None:
            self.next_allocation = self.schedule(self.get_allocation, delay=self.max_allocation.duration)
        else:
            self.next_allocation = self.schedule(self.get_allocation, delay=self.generate_allocations_period)

    def update_measure(self):
        if self.update_measure_cb is not None:
            try:
                measure = self.update_measure_cb(self.curr_allocation, self.local, time())
            except Exception as e:
                self.logger.warning("Couldn't update measure: {}".format(e))
            if measure is not None:
                self.curr_measure = measure
                self.logger.info("New measure is {}v".format(measure))
        self.report_measure()
        self.schedule(action=self.update_measure, delay=self.update_measure_period)

    def report_measure(self):
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
            packet = Packet('join', [self.curr_allocation, None], src=self.local, dst=dst)
            self.join_ack_timer = self.schedule(
                    action=lambda msg: self.logger.info(msg),
                    args=['no join ack from {}'.format(dst)],
                    delay=self.join_ack_timeout)
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
        self.logger.info("sending allocation_ack {} to {}".format(allocation[0].aid, self.local))
        packet = Packet('allocation_ack', allocation, src=self.local, dst=dst)

        self.send(packet, dst)

    def send_leave(self, dst):
        self.logger.info("Leaving {}".format(dst))

        packet = Packet(ptype='leave', src=self.local, dst=dst)

        self.send(packet, dst)

    def stop(self):
        # Stop underlying simpy event loop
        self.logger.info("Stopping Simpy")
        self.remote = None
        super(NetworkLoad, self).stop()
