from abc import abstractmethod
from sys import float_info
import hashlib
import simpy
from async_communication import AsyncCommunication
from defs import Packet, Allocation, EventId
import logging
logger = logging.getLogger('Agent')
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
        self.logger = logging.getLogger('Agent')

        self.env = simpy.rt.RealtimeEnvironment(strict=False) if env is None else env
        self.timeouts = {}

    def run(self):
        self.logger.info("started agent's infinite loop")
        try:
            self.env.run(until=float_info.max)
        except (KeyboardInterrupt, simpy.Interrupt) as e:
            self.logger.debug("{}".format(e))

    def schedule(self, action, args=None, time=0, value=None):
        """ The agent's schedule function

        :param time: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :returns:
        :rtype:

        """
        self.logger.debug("scheduling action {}".format(action))
        event = self.env.event()
        event._ok = True
        event._value = value
        # event = self.env.timeout(delay=time, value=value)
        event.callbacks.append(
            lambda e: self.logger.debug("executing action{}".format(action)))
        if args is None:
            event.callbacks.append(
                lambda e: action())
        else:
            event.callbacks.append(
                lambda e: action(**args))
        self.env.schedule(event=event, delay=time)
        return event

    def stop(self):
        """ stop the Agent.
        Behavior left for child classes

        :returns:
        :rtype:

        """
        self.logger.debug("interrupting pending timeouts")
        for _,v in self.timeouts.items():
            if not v.processed and not v.triggered:
                v.interrupt()
        if len(self.timeouts) > 0:
            self.logger.warning("remained {} timeouts not interrupted".format(len(self.timeouts)))
        stop_event = self.env.timeout(0)
        stop_event.callbacks.append(simpy.core.StopSimulation.callback)

    def create_timer(self, timeout, eid, msg=''):
        self.logger.debug("creating timer {} for {}s".format(eid, timeout))
        event = self.env.timeout(timeout, value=eid)
        event.callbacks.append(
            lambda event: self.logger.info("timeout expired\n {}".format(msg)))
        event.callbacks.append(
            lambda event: self.remove_timer(eid))
        self.timeouts[eid] = event

    def remove_timer(self, eid):
        self.logger.debug("canceling timer {}".format(eid))
        e = self.timeouts.pop(eid, None)
        if e is None:
            self.logger.warning("no eid %s"%eid)
        # if e is not None and not (e.processed or e.triggered):
        self.schedule(e.interrupt)
