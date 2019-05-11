# -*- coding: utf-8 -*-

import logging
import queue
import time
from abc import ABCMeta
from heapq import heappush, heappop
from random import Random
from threading import Thread

import simpy
from simpy.core import Environment, Infinity, NORMAL
from simpy.events import PENDING

from .async_communication import AsyncCommunication
from .defs import Packet

logger = logging.getLogger(__name__)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

# logger.setLevel(logging.INFO)
# ch.setLevel(logging.INFO)


class ErrorModel(object):
    def __init__(self, rate=1.0, seed=None):
        self.rate = rate
        self.ran = Random(seed)

    def corrupt(self, packet):
        return self.ran.random() >= self.rate


class AgentEnvironment(Environment):
    def __init__(self, initial_time=0):
        self.initial_time = initial_time
        super(AgentEnvironment, self).__init__(initial_time)

    def schedule(self, event, priority=NORMAL, delay=0):
        """
        Schedule an *event* with a given *priority* and a *delay*.
        Scheduling relatively to real now
        """
        heappush(self._queue,
                 (time.time() + delay, priority, next(self._eid), event))

    def step(self):
        """Process the next event.

        Raise an :exc:`EmptySchedule` if no further events are available.

        """
        try:
            self._now, _, _, event = heappop(self._queue)
        except IndexError:
            raise EmptySchedule()

        if not event._ok and not hasattr(event, '_defused'):
            # The event has failed and has not been defused. Crash the
            # environment.
            # Create a copy of the failure exception with a new traceback.
            exc = type(event._value)(*event._value.args)
            exc.__cause__ = event._value
            raise exc
        if not event._ok:
            return

        # Process callbacks of the event. Set the events callbacks to None
        # immediately to prevent concurrent modifications.
        callbacks, event.callbacks = event.callbacks, None
        for callback in callbacks:
            callback(event)

    @property
    def now(self):
        """The current simulation time."""
        return self._now - self.initial_time

# A generic Network Agent.


class Agent(object, metaclass=ABCMeta):
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        self.env = env
        self.nid = None
        self.type = None
        self.tasks = queue.Queue()
        self._local = None
        self.comm = AsyncCommunication()
        self.comm._callback = self.receive
        self._error_model = None
        self._sim_thread = Thread(target=self._run)
        self.logger = None

    @property
    def error_model(self):
        return self._error_model

    @error_model.setter
    def error_model(self, model):
        self._error_model = model

    @property
    def local(self):
        return self._local

    @local.setter
    def local(self, value):
        self._local = value
        self.comm._local_address = value
        if self.comm.running:
            self.comm.stop()
            self.comm._local_address = value
            self.comm.start()

    @property
    def callback(self):
        return self.comm._callback

    @callback.setter
    def callback(self, value):
        self.comm._callback = value

    @property
    def identity(self):
        return self.comm._identity

    @identity.setter
    def identity(self, value):
        self.comm._identity = value

    def run(self):
        self.logger = logging.getLogger(
            '{}.{}.{}'.format(__name__, self.type, self.local))
        self.comm.start()
        self._sim_thread.start()

    def _run(self):
        self.env = AgentEnvironment(time.time())
        self.logger.info("started {} agent's infinite loop".format(self.type))
        while True:
            delay = self.env.peek() - time.time()
            if delay <= 0:
                try:
                    self.env.step()
                except BaseException as e:
                    self.logger.info(e)
                continue
            try:
                func = self.tasks.get(
                    timeout=None if delay == Infinity else delay)
            except queue.Empty:
                continue
            if not func:
                self.env = None
                return
            try:
                func(self.env)
            except Exception as e:
                self.logger.warning("Error executing function {}: {}".format(func, e))
                raise(e)

    def schedule(self, action, args=None, delay=0, value=None, callbacks=None):
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
        if not isinstance(self.env, Environment):
            self.logger.warning(
                "Scheduling failed, Agent Environment not ready!")
            return

        if callbacks is None:
            callbacks = []
        self.logger.debug(
            "scheduling action {} at {}".format(action, self.env.now))

        event = self.env.event()
        event._ok = True
        event._value = PENDING
        event.callbacks.append(lambda e: self.logger.debug(
            "executing action{}".format(action)))
        def action_worker(event, fn, args):
            try:
                if args is None:
                    action()
                elif isinstance(args, dict):
                    action(**args)
                elif isinstance(args, list):
                   action(*args)
            except Exception as e:
                self.logger.warning("Failed in action_worker for {}".format(action))
        
        event.callbacks.append(lambda e: action_worker(event, action, args))       
        for callback in callbacks:
            event.callbacks.append(lambda e: callback())

        def task(env): return env.schedule(event=event, delay=delay)
        self.tasks.put(task)
        return event

    def stop(self):
        """ stop the Agent by interrupted the loop"""
        # Schedule None to trigger Agent's loop termination
        self.tasks.put(None)
        self.comm.stop()

    def interrupt_event(self, event):
        try:
            event.fail(BaseException("Interrupted"))
        except Exception as e:
            self.logger.warning("interrupt_event failed: {}".format(e))

    def send(self, packet: Packet, remote: str):
        if isinstance(self._error_model, ErrorModel):
            if not self._error_model.corrupt(packet):
                self.comm.send(packet, remote)
            else:
                self.logger.info("packet error occurred at Agent.send")
        else:
            self.comm.send(packet, remote)

    def receive(self, packet, src=None):
        self.logger.info("receiving {}".format(packet))
        if isinstance(self._error_model, ErrorModel):
            if not self._error_model.corrupt(packet):
                self.receive_handle(packet, src)
            else:
                self.logger.info("packet error occurred at Agent.receive")
        else:
            self.receive_handle(packet, src)

    def receive_handle(self, packet, src=None):
        raise NotImplementedError("must override receive_handle")
