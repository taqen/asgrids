from .defs import Packet, Allocation, EventId
from .agent import Agent
from .async_communication import AsyncCommunication
import simpy
import typing

class NetworkLoad(Agent):
    def __init__(self, local=None, remote=None, env=None):
        super(NetworkLoad, self).__init__(env=env)
        self.remote = remote
        self.nid = self.local
        self.curr_allocation = Allocation()
        self.local = local
        self.callback = self.handle_receive
        self.identity = self.nid
        self.type = "NetworkLoad"
        # storage for current electrical measures
        self.curr_measure = 0
        # callback to call when reporting allocation, to get current electrical measures.
        self.update_measure :Callable = None
        # callback to call when node received join_ack
        self.joined_callback :Callable = None
        # callback to generate allocation values for this NetworkLoad
        self.generate_allocations :Callable = None
        # Event that will trigger handle_allocation for next value
        self.next_allocation = None

    def handle_receive(self, p, src=None):
        """ Handled payload received from AsyncCommunication

        :param p: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p

        self.logger.warning("handling {} from {}".format(p, p.src))
        msg_type = p.ptype

        if msg_type == 'join_ack':
            self.logger.info("Joined successfully allocator {}".format(p.src))
            self.remote = p.src
            if self.joined_callback is not None:
                self.joined_callback(self.local, self.remote)

        if msg_type == 'allocation':
            # Interrupting any pending next allocation
            # because allocator demands take priority
            if self.next_allocation is not None:
                self.next_allocation.interrupt()
                self.next_allocation = None

            allocation = p.payload
            self.logger.debug("allocation={}".format(allocation))
            self.schedule(
                action=self.send_ack,
                args={
                    'allocation': allocation,
                    'dst': p.src
                })
            self.schedule(
                action=self.handle_allocation,
                args={'allocation': allocation})

        if msg_type == 'stop':
            self.logger.info("Received Stop from {}".format(p.src))
            self.send(Packet(ptype='stop_ack', src=self.local), p.src)
            self.schedule(self.stop)

    def handle_allocation(self, allocation):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        self.logger.info(
            "{} - Current allocation value is {}".format(
            self.local,
            self.curr_allocation)
            )

        self.curr_allocation = allocation

        self.logger.info(
            "{} - New allocation value is {}".format(
            self.local,
            self.curr_allocation)
            )
        self.schedule(self.report_allocation)

        if self.generate_allocations is not None:
            self.logger.info("Scheduling allocation generation")
            self.next_allocation = self.schedule(
                                        self.handle_allocation,
                                        {'allocation':self.generate_allocations(self.local, self.curr_allocation)},
                                        delay=self.curr_allocation.duration)

    def report_allocation(self):
        if self.remote is not None:
            self.logger.info("Reporting allocation {} to {}".format(self.curr_allocation, self.remote))
            if self.update_measure is not None:
                measure = self.update_measure(self.curr_allocation, self.local)
                if measure is not None:
                    self.curr_measure = measure
                    self.logger.info("New measure is {}".format(measure))
            packet = Packet('curr_allocation', self.curr_allocation, self.local)
            self.send(packet, self.remote)
        else:
            self.logger.info("Not reporting, remote not defined yet")

    def send_join(self, dst):
        """ Send a join request to the allocator

        :param dst: destination address of the allocator
        :returns:
        :rtype:

        """
        self.logger.info('{} Joining {}'.format(self.local, dst))
        packet = Packet('join', self.curr_allocation, self.local)
        self.send(packet, dst)

    def send_ack(self, allocation, dst):
        """ Acknowledge a requested allocation to the Allocator.

        :param allocation: allocation that is processed
        :param dst: destination address of the Allocator
        :returns:
        :rtype:

        """
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