from defs import Packet, Allocation, EventId
from agent import Agent
from async_communication import AsyncCommunication
import logging
import simpy
logger = logging.getLogger('Agent.NetworkLoad')

class NetworkLoad(Agent):
    def __init__(self, remote='127.0.0.1:5555', local='127.0.0.1:5000', env=None):
        self.remote = remote
        self.local = local
        self.nid = self.local
        self.curr_allocation = Allocation()
        self.comm = AsyncCommunication(callback=self.receive_handle,
                                       local_address=local,
                                       identity=self.nid)
        self.comm.start()
        super(NetworkLoad, self).__init__(env=env)

        loggername = 'Agent.NetworkLoad.{}'.format(local.split(':')[1])
        self.logger = logging.getLogger(loggername)
        self.logger.info("initializing")

    def receive_handle(self, p, src):
        """ Handled payload received from AsyncCommunication

        :param p: payload received
        :param src: source of payload
        :returns:
        :rtype:

        """
        self.logger.info("handling {} from {}".format(p, src))
        msg_type = p.ptype
        if msg_type == 'join_ack':
            self.logger.info("Joined successfully allocator {}".format(src))
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
            self.comm.send(Packet(ptype='stop_ack', src=self.nid), src)
            if p.payload == 'force':
                self.stop(force=True)
            else:
                self.stop(force=False)

    def allocation_handle(self, allocation):
        """ Handle a received allocation

        :param allocation: the allocation duration and value to be processed.
        :returns:
        :rtype:

        """
        self.logger.info(
            "{} - Current node is {}".format(
            self.nid,
            self.curr_allocation['allocation_value'])
            )

        self.curr_allocation = allocation

        self.logger.info(
            "{} - Updated node is {}".format(
            self.nid,
            allocation['allocation_value'])
            )
        #yield self.env.timeout(0)
        #yield self.env.timeout(allocation.duration)

    def allocation_report(self):
        packet = Packet('curr_allocation', self.curr_allocation, self.nid)

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
        self.logger.info("Leaving {}".format(dst))
    
        packet = Packet(ptype='leave', src=self.nid)

        self.comm.send(packet, dst)

    def stop(self, force=False):
        # Stop underlying simpy event loop
        super(NetworkLoad, self).stop(force=force)
        # Inform AsyncCommThread we are stopping
        self.comm.stop()
        # Wait for asyncio thread to cleanup properly
        self.comm.join()
