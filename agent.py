from abc import abstractmethod
from sys import int_info
import hashlib
import simpy
from scheduler import SinsEnvironment
from async_communication import AsyncCommunication
from defs import Packet, Allocation, EventId
import logging
from time import time
from simpy.core import Infinity
import queue

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

        self.env = None # = SinsEnvironment(strict=True, factor=0.1) if env is None else env
        self.tasks = queue.Queue()
        self.timeouts = {}

    def run(self):
        self.env = simpy.Environment(time())
        self.logger.info("started agent's infinite loop")
        # sleep for max value of int64_t = 9223372036.854775
        # see:
        # https://github.com/python/cpython/blob/f2f4555d8287ad217a1dba7bbd93103ad4daf3a8/Include/pytime.h#L19
        # self.env.run(until=9223372036.854775)
        while True:
            delay = self.env.peek() - time()
            if delay <= 0:
                self.env.step()
                continue
            try:
                func = self.tasks.get(timeout = None if delay == Infinity else delay)
            except queue.Empty:
                continue
            if not func:
                return
            func()

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
        self.tasks.put(lambda: self.env.schedule(event=event, delay=time))
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

        self.tasks.put(None)
        # stop_event = self.env.event()
        # stop_event._ok = True
        # stop_event._value = None
        # stop_event.callbacks.append(lambda e: logger.info("Triggering simpy StopSimulation"))
        # stop_event.callbacks.append(simpy.core.StopSimulation.callback)
        # self.env.schedule(stop_event, simpy.core.URGENT, 0)

    def create_timer(self, timeout, eid, msg=''):
        self.logger.warning("creating timer {} for {}s".format(eid, timeout))
        def event_process():
            yield self.env.timeout(timeout, value=eid)
            self.logger.warning("timeout {} expired at {}: {}".format(eid, self.env.now, msg))
            self.schedule(self.remove_timeout, args={'eid':eid})
        event = self.env.process(event_process())
        self.timeouts[eid] = event

    def remove_timeout(self, eid):
        self.logger.warning("canceling timer {}".format(eid))
        e = self.timeouts.pop(eid, None)
        if e is None:
            self.logger.warning("no eid %s"%eid)
            return
        # if e is not None and not (e.processed or e.triggered):
        try:
            e.interrupt()
            self.logger.warning("canceled timer {} at {}".format(eid, self.env.now))
        except Exception as e:
            self.logger.warning("ERROR INTERRUPTING TIMEOUT {} \n {}".format(eid,e))
