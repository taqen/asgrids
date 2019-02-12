#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import queue
import time
from abc import ABCMeta
from heapq import heappush
from random import Random
from threading import Thread

import simpy
from simpy.core import Environment, Infinity, NORMAL

from .async_communication import AsyncCommunication

logger = logging.getLogger('Agent')


# logger.setLevel(logging.INFO)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setLevel(logging.INFO)
# ch.setFormatter(formatter)
# logger.addHandler(ch)

class ErrorModel(object):
    def __init__(self, rate=1.0, seed=None):
        self.rate = rate
        self.ran = Random(seed)

    def corrupt(self, packet):
        return self.ran.random() >= self.rate


class AgentEnvironment(Environment):
    def schedule(self, event, priority=NORMAL, delay=0):
        """
        Schedule an *event* with a given *priority* and a *delay*.
        Scheduling relatively to real now
        """
        heappush(self._queue,
                 (time.time() + delay, priority, next(self._eid), event))


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
        self.timeouts = dict()
        self._local = None
        self.comm = AsyncCommunication()
        self.comm._callback = self.receive
        self._error_model = ErrorModel()
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
        self.logger = logging.getLogger('Agent.{}.{}'.format(self.type, self.local))
        self.comm.start()
        self._sim_thread.start()

    def _run(self):
        self.env = AgentEnvironment(time.time())
        self.logger.info("started {} agent's infinite loop".format(self.type))
        while True:
            delay = self.env.peek() - time.time()
            if delay <= 0:
                self.env.step()
                continue
            try:
                func = self.tasks.get(timeout=None if delay == Infinity else delay)
            except queue.Empty:
                continue
            if not func:
                self.env = None
                return
            try:
                func(self.env)
            except Exception as e:
                raise RuntimeError(e)

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
        if callbacks is None:
            callbacks = list()
        self.logger.debug("scheduling action {} at {}".format(action, time.time()))
        event = self.env.event()
        event._ok = True
        event._value = value
        event.callbacks.append(
            lambda e: self.logger.debug("executing action{}".format(action)))
        if args is None:
            event.callbacks.append(lambda e: action())
        elif isinstance(args, dict):
            event.callbacks.append(lambda e: action(**args))
        elif isinstance(args, list):
            event.callbacks.append(lambda e: action(**args))
        for callback in callbacks:
            event.callbacks.append(lambda e: callback())

        self.tasks.put(lambda env: env.schedule(event=event, delay=delay))
        # return event

    def stop(self):
        """ stop the Agent by interrupted the loop"""

        self.logger.debug("interrupting pending timeouts")
        for _, v in self.timeouts.items():
            if not v.processed and not v.triggered:
                v.interrupt()
        if len(self.timeouts) > 0:
            self.logger.warning("remained {} timeouts not interrupted".format(len(self.timeouts)))

        # Schedule None to trigger Agent's loop termination
        self.tasks.put(None)
        self.comm.stop()

    def create_timeout(self, timeout, eid, msg=''):
        """
        Creating a timer using simpy's timeout.
        A timer will clear itself from Agents timeouts list after expiration.
        """
        self.logger.debug("creating timer {} for {}s".format(eid, timeout))

        def event_process():
            try:
                yield self.env.timeout(timeout, value=eid)
            except simpy.exceptions.Interrupt:
                # self.logger.warning("event_process interrupted for eid {}".format(eid))
                return
            self.logger.warning("timeout {} expired at {}: {}".format(eid, self.env.now, msg))
            self.schedule(self.remove_timeout, args={'eid': eid})

        event = self.env.process(event_process())
        return event
        # self.timeouts[eid] = event

    def remove_timeout(self, eid):
        """
        Remove a timeout from Agent's timeouts
        """
        self.logger.debug("canceling timer {}".format(eid))
        e = self.timeouts.pop(eid, None)
        if e is None:
            self.logger.warning("remote_timeout, no eid %s" % eid)
            return
        # if e is not None and not (e.processed or e.triggered):
        try:
            e.interrupt()
            self.logger.debug("canceled timer {} at {}".format(eid, self.env.now))
        except Exception as e:
            self.logger.warning("remote_timeout, couldn't interrupt timeout {} \n {}".format(eid, e))

    def send(self, packet, remote):
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
