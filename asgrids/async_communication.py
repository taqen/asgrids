#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import msgpack
import zmq
import zmq.asyncio

from .defs import ext_pack, ext_unpack, Packet

logger = logging.getLogger(__name__)


# logger.setLevel(logging.DEBUG)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setLevel(logging.DEBUG)
# ch.setFormatter(formatter)
# logger.addHandler(ch)

class AsyncCommunication(threading.Thread):
    def __init__(self, local_address=None, callback=None, identity=None):

        self._identity = identity
        self._callback = callback
        self._local_address = local_address
        self._timeout = 1000
        self.running = False
        self._loop = asyncio.new_event_loop()
        try:
            self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='executor')
        except TypeError:
            # Python 3.5
            self._executor = ThreadPoolExecutor(max_workers=10)
        self._loop.set_default_executor(self._executor)
        asyncio.set_event_loop(self._loop)
        self._context = zmq.asyncio.Context()
        self._poller = zmq.asyncio.Poller()
        self._clients = {}
        self.event = asyncio.Event(loop=self._loop)
        name = 'AsyncCommThread'
        threading.Thread.__init__(self, name=name)

    def run(self):
        server_future = asyncio.ensure_future(self._run_server(), loop=self._loop)
        try:
            self._loop.run_until_complete(server_future)
        finally:
            self._loop.close()

    async def _send(self, request: Packet, remote):
        if remote not in self._clients:
            try:
                self._clients[remote] = self._context.socket(zmq.DEALER)
                # No lingering after socket is closed.
                # This has proven to cause problems terminating asyncio when lingering infinitely
                self._clients[remote].setsockopt(zmq.LINGER, 0)
                # self._poller.register(self._client, zmq.POLLIN)
            except Exception as e:
                logger.error(e)
                raise e

        try:
            p = msgpack.packb(request, default=ext_pack, strict_types=True, encoding='utf-8')
        except Exception as e:
            logger.error("Error packing {}".format(e))
            raise e

        try:
            socket_address = 'tcp://{}'.format(remote)
            logger.info("{} connecting to {}".format(self._local_address, socket_address))
            self._clients[remote].connect(socket_address)
            logger.info('{} sending {} to {}'.format(self._local_address, request, socket_address))
            await self._clients[remote].send_multipart([p])
        except zmq.ZMQError as zmqerror:
            logger.error("Error connecting client socket to address {}. {}".format(socket_address, zmqerror))
            return

    async def _run_server(self):
        if self._local_address is None:
            logger.warning('local_address not set')
            raise ValueError(self._local_address)
        if self._callback is None:
            logger.warning('callback is not set')
            raise ValueError(self._callback)
        logger.warning('Server listening on address tcp://{}.'.format(self._local_address))

        self._server = self._context.socket(zmq.ROUTER)
        self._server.bind('tcp://{}'.format(self._local_address))
        self._poller.register(self._server, zmq.POLLIN)
        logger.info('running server on tcp://{}.'.format(self._local_address))
        while not self.event.is_set():
            items = dict(await self._poller.poll(self._timeout))
            if self._server in items and items[self._server] == zmq.POLLIN:
                logger.info("receiving at server {}".format(self._local_address))
                _, msg = await self._server.recv_multipart()
                try:
                    p = msgpack.unpackb(msg, ext_hook=ext_unpack, encoding='utf-8')
                    # ident = msgpack.unpackb(ident, encoding='utf-8')
                except Exception as e:
                    raise e
                logger.debug('server received {}'.format(p))
                await self._loop.run_in_executor(self._executor, self._callback, p)
        logger.info("stopping server")
        self._poller.unregister(self._server)
        self._server.close()

    def send(self, request, remote):
        logger.debug("send {} to {}".format(request, remote))
        try:
            asyncio.run_coroutine_threadsafe(
                self._send(request=request, remote=remote), self._loop)
        except Exception as e:
            logger.warning(e)

    def stop(self):
        logger.info("Stopping AsyncCommThread")
        try:
            self._loop.call_soon_threadsafe(self.event.set)
        except Exception as e:
            logger.warning(e)
        # self._poller.unregister(self._client)
        for remote in self._clients:
            self._clients[remote].close()
