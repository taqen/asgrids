#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import msgpack

from .defs import ext_pack, ext_unpack, Packet

logger = logging.getLogger(__name__)


# logger.setLevel(logging.DEBUG)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setLevel(logging.DEBUG)
# ch.setFormatter(formatter)
# logger.addHandler(ch)

class AsyncUdpProtocol:
    def __init__(self, callback, loop):
        self.loop = loop
        self.handle_income_packet = callback
        self.transport = None
        self.on_con_lost = loop.create_future()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.loop.create_task(self.handle_income_packet(data, addr))

    def error_received(self, exc):
        # print('Error received:', exc)
        pass
    def connection_lost(self, exc):
        # print("Connection closed")
        self.on_con_lost.set_result(True)


class AsyncUdp(threading.Thread):
    def __init__(self, local_address=None, callback=None):

        self._callback = callback
        self._local_address = local_address
        self._loop = None
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='executor')
        self.protocol = None
        self.transport = None
        self.event = None
        name = 'AsyncUdpThread'
        threading.Thread.__init__(self, name=name)

    async def udp_loop(self):
        self._loop = asyncio.get_event_loop()
        self._loop.set_default_executor(self._executor)
        self.running = True
        self.event = asyncio.Event(loop=self._loop)
        ipaddr, port = self._local_address.split(':')
        port = int(port)
        try:
            self.transport, self.protocol = await self._loop.create_datagram_endpoint(
                lambda: AsyncUdpProtocol(self._receive, self._loop), local_addr=(ipaddr, port))
        except Exception as e:
            logger.warning(e)

        await self.event.wait()
        logger.debug("Closing udp loop")
        try:
            self.transport.abort()
            self.transport.close()
        except Exception as e:
            logger.warning(e)
        logger.debug("Closed udp loop")

    def run(self):
        asyncio.run(self.udp_loop())
        logger.debug("Closing asyncio")

    def send(self, request, remote):
        p = msgpack.packb(request, default=ext_pack, strict_types=True, encoding='utf-8')
        ipaddr, port = remote.split(':')
        port = int(port)
        if self.transport:
            try:
                self.transport.sendto(p, (ipaddr, port))
            except Exception as e:
                logger.warning(e)

    async def _receive(self, data, addr):
        if not self.running:
            return
        p = msgpack.unpackb(data, ext_hook=ext_unpack, encoding='utf-8')
        await self._loop.run_in_executor(self._executor, self._callback, p)

    def stop(self):
        logger.debug("Stopping AsyncUdpThread")
        # self._poller.unregister(self._client)
        try:
            self._loop.call_soon_threadsafe(self.event.set)
        except Exception as e:
            logger.warning(e)