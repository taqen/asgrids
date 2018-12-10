from abc import abstractmethod
from sys import int_info
import hashlib
from simpy.core import Environment, NORMAL, Infinity
from heapq import heappush
from async_communication import AsyncCommunication
from defs import Packet, Allocation, EventId
import logging
from time import time
import queue

logger = logging.getLogger('Agent')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)


class AgentEnvironment(Environment):
    def schedule(self, event, priority=NORMAL, delay=0):
        """
        Schedule an *event* with a given *priority* and a *delay*.
        Scheduling relatively to real now
        """
        heappush(self._queue,
                 (time() + delay, priority, next(self._eid), event))

# A generic Network Agent.
class Agent():
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        self.logger = logging.getLogger('Agent')
        self.env = None
        self.tasks = queue.Queue()
        self.timeouts = {}

    def run(self):
        self.env = AgentEnvironment(time())
        self.logger.info("started agent's infinite loop")
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
        """
        The agent's schedule function.
        First it creates a simpy events, that will then execute the action
        when triggered.
        The event is scheduled in the tasks queue, to be dequeued in the agent's
        loop.

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
        """ stop the Agent by interrupted the loop"""

        self.logger.debug("interrupting pending timeouts")
        for _,v in self.timeouts.items():
            if not v.processed and not v.triggered:
                v.interrupt()
        if len(self.timeouts) > 0:
            self.logger.warning("remained {} timeouts not interrupted".format(len(self.timeouts)))

        # Schedule None to trigger Agent's loop termination
        self.tasks.put(None)

    def create_timer(self, timeout, eid, msg=''):
        """
        Creating a timer using simpy's timeout.
        A timer will clear itself from Agents timeouts list after expiration.
        """
        self.logger.warning("creating timer {} for {}s".format(eid, timeout))
        def event_process():
            yield self.env.timeout(timeout, value=eid)
            self.logger.warning("timeout {} expired at {}: {}".format(eid, self.env.now, msg))
            self.schedule(self.remove_timeout, args={'eid':eid})
        event = self.env.process(event_process())
        self.timeouts[eid] = event

    def remove_timeout(self, eid):
        """
        Remove a timeout from Agent's timeouts
        """
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
            self.logger.warning("Couldn't interrupt timeout {} \n {}".format(eid,e))
