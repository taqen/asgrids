from .defs import Packet, Allocation, EventId
from .agent import Agent
from .async_communication import AsyncCommunication
import simpy

class NetworkLoad(Agent):
    def __init__(self, local=None, remote=None, env=None):
        super(NetworkLoad, self).__init__(env=env)
        self.remote = remote
        self.nid = self.local
        self.curr_allocation = Allocation()
        self.local = local
        self.callback = self.receive_handle
        self.identity = self.nid
        self.type = "NetworkLoad"

    def receive_handle(self, p, src=None):
        """ Handled payload received from AsyncCommunication

        :param p: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        assert isinstance(p, Packet), p
        src = src
        if src is None:
            src = p.src

        self.logger.info("handling {} from {}".format(p, src))
        msg_type = p.ptype
        if msg_type == 'join_ack':
            self.logger.info("Joined successfully allocator {}".format(src))
            self.remote = src
        if msg_type == 'allocation':
            allocation = p.payload
            self.logger.debug("allocation={}".format(allocation))
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
            self.logger.info("Received Stop from {}".format(src))
            self.comm.send(Packet(ptype='stop_ack', src=self.local), src)
            self.schedule(self.stop)


    def allocation_handle(self, allocation):
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

        #yield self.env.timeout(0)
        #yield self.env.timeout(allocation.duration)

    def allocation_report(self):
        packet = Packet('curr_allocation', self.curr_allocation, self.local)

        self.logger.info("Reporting allocation {} to {}".format(self.curr_allocation, self.remote))

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
        self.logger.info('Joining {}'.format(dst))
        packet = Packet('join', self.curr_allocation, self.local)
        self.comm.send(packet, dst)

    def send_ack(self, allocation, dst):
        """ Acknowledge a requested allocation to the Allocator.

        :param allocation: allocation that is processed
        :param dst: destination address of the Allocator
        :returns:
        :rtype:

        """
        packet = Packet('allocation_ack', allocation, self.local)

        self.comm.send(packet, dst)

    def send_leave(self, dst):
        self.logger.info("Leaving {}".format(dst))
    
        packet = Packet(ptype='leave', src=self.local)

        self.comm.send(packet, dst)

    def stop(self):
        # Stop underlying simpy event loop
        self.logger.info("Stopping Simpy")
        super(NetworkLoad, self).stop()