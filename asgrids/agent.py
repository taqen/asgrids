# -*- coding: utf-8 -*-

import logging
import queue
from time import monotonic as time
from abc import ABCMeta
from heapq import heappush, heappop
from random import Random
from threading import Thread, Event

import asyncio
from .async_udp_communication import AsyncUdp
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



# A generic Network Agent.


class Agent(object, metaclass=ABCMeta):
    def __init__(self, mode='udp'):
        """ Make sure a simulation environment is present and Agent is running.

        """
        self.nid = None
        self.type = None
        self._local = None
        if mode == 'udp':
        self.comm = AsyncUdp()
        elif mode == 'tcp':
            self.comm = AsyncCommunication()
        else:
            raise ValueError(mode)
        self.comm._callback = self.receive
        self._error_model = None
        self._sim_thread = Thread(target=self._run)
        self.logger = None
        self.loop = None
        self.event = None
        self.is_running = Event()

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
        # if self.comm.event and not self.comm.event.is_set():
        #     self.comm.stop()
        #     self.comm._local_address = value
        #     self.comm.start()

    @property
    def callback(self):
        return self.comm._callback

    @callback.setter
    def callback(self, value):
        self.comm._callback = value

    async def agent_loop(self):
        self.event = asyncio.Event()
        self.loop = asyncio.get_event_loop()
        self.loop.set_exception_handler(self.loop_exception_handler)
        self.is_running.set()
        await self.event.wait()
        self.logger.info("stopped {} agent's infinite loop".format(self.type))

    def run(self):
        self.logger = logging.getLogger(
            '{}.{}.{}'.format(__name__, self.type, self.local))
        self.comm.start()
        self._sim_thread.start()
        

    def _run(self):
        self.logger.info("started {} agent's infinite loop".format(self.type))
        asyncio.run(self.agent_loop())

    async def call_later(self, delay, action, args):
        await asyncio.sleep(delay)
        self.logger.debug("calling_soon {}".format(action))
        self.loop.call_soon(action, *args)

    def schedule(self, action, args=None, delay=0, callbacks=None):
        """
        The agent's schedule function.

        :param delay: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :param args: actions' arguments.
        :returns:
        :rtype:

        """
        self.is_running.wait()
        if callbacks is None:
            callbacks = []
        if args is None:
            args = []
        self.logger.debug("scheduling {} after {} seconds".format(action, delay))
        try:
            coro = self.call_later(delay, action, args)
        except Exception as e:
            self.logger.debug(f'The coroutine raised an exception: {e!r}')
        try:
            event = asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception as e:
            if self.loop.is_running():
                self.logger.warning(f'The coroutine raised an exception: {e!r}')
            return None
        msg = "Executing {} after {}s".format(action, delay)
        event.add_done_callback(lambda x: self.logger.debug(msg))
        for cb in callbacks:
            event.add_done_callback(cb)
        return event

    def stop(self):
        """ stop the Agent by interrupted the loop"""
        # Schedule None to trigger Agent's loop termination
        try:
            self.loop.call_soon_threadsafe(self.event.set)
        except Exception as e:
            self.logger.warning(e)
        self.comm.stop()

    def interrupt_event(self, event):
        if event is None:
            return
        try:
            event.cancel()
        except Exception as e:
            self.logger.warning(f"interrupt_event failed: {e!r}")

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

    def loop_exception_handler(self, obj, context):
        self.logger.debug(context['message'])