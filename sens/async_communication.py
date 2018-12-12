#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import logging
import threading

import zmq
import zmq.asyncio
from concurrent.futures import ThreadPoolExecutor
import msgpack
from .defs import ext_pack, ext_unpack

# Get the local logger
logger = logging.getLogger('AsyncCommThread')
# logger.setLevel(logging.DEBUG)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setLevel(logging.DEBUG)
# ch.setFormatter(formatter)
# logger.addHandler(ch)

class AsyncCommunication():
    def __init__(self, local_address = None, callback=None, identity=None):

        self._receive_callback = None
        self._identity = identity
        self._callback = callback
        self._local_address = local_address
        self._client = None
        self._server = None
        self._timeout = 1000
        self._running = False
        self._context = zmq.asyncio.Context()
        self._poller = zmq.asyncio.Poller()
        self._loop = asyncio.new_event_loop()
        self._executor = ThreadPoolExecutor(max_workers=10,
                                           thread_name_prefix='executor')
        self._loop.set_default_executor(self._executor)

    def run(self):
        asyncio.set_event_loop(self._loop)
        self.running = True
        server_future = asyncio.ensure_future(
            self._run_server(),
            loop=self._loop)
        try:
            self._loop.run_until_complete(server_future)
        finally:
            self._loop.close()

    async def _send(self, request, remote=None):
        if self._client is None:
            logger.debug("creating client")
            self._client = self._context.socket(zmq.DEALER)
            # No lingering after socket is closed.
            # This has proven to cause problems terminating asyncio if not 0
            self._client.setsockopt(zmq.LINGER, 100)

        if self._identity is not None:
            logger.info("identity is %s" % self._identity)
            identity = msgpack.packb(self._identity, encoding='utf-8')
            try:
                self._client.setsockopt(zmq.IDENTITY, identity)
            except zmq.ZMQError as zmqerror:
                logger.error("Error setting socket identity. {}".format(zmqerror))

        assert remote is not None, 'no socket_address provided'

        socket_address = 'tcp://{}'.format(remote)

        logger.info("Connecting to {}".format(socket_address))
        try:
            self._client.connect(socket_address)
            self._poller.register(self._client, zmq.POLLIN)
        except zmq.ZMQError as zmqerror:
            logger.error("Error connecting client socket. {}".format(zmqerror))
            raise zmqerror

        try:
            p = msgpack.packb(request, default=ext_pack, strict_types=True, encoding='utf-8')
        except Exception as e:
            logger.error("Error packing {}".format(e))

        logger.info('sending {} to {}'.format(request, socket_address))
        await self._client.send_multipart([p])
        self._poller.unregister(self._client)
        self._client.close()
        self._client = None

    async def _run_server(self):
        assert self._local_address is not None, 'local_address not set'
        assert self._callback is not None, 'callback is not set'
        logger.debug('Server listening on address tcp://{}.'.format(self._local_address))

        self._server = self._context.socket(zmq.ROUTER)
        self._server.bind('tcp://{}'.format(self._local_address))
        self._poller.register(self._server, zmq.POLLIN)
        logger.info('running server')
        try:
            while self.running:
                items = dict(await self._poller.poll(self._timeout))
                if self._server in items and items[self._server] == zmq.POLLIN:
                    logger.debug("receiving at server")
                    ident, msg = await self._server.recv_multipart()
                    p = msgpack.unpackb(msg, ext_hook=ext_unpack, encoding='utf-8')
                    ident = msgpack.unpackb(ident, encoding='utf-8')
                    logger.debug('server received {} from {}'.format(p, ident))
                    await self._loop.run_in_executor(self._executor,
                                                    self._callback,
                                                    p,
                                                    ident)
        except KeyboardInterrupt:
            logger.debug("async_communication loop interrupted")
        finally:
            logger.info("stopping server")
            self._poller.unregister(self._server)
            self._server.close()

    def send(self, request, remote=None):
        logger.debug("send {} to {}".format(request, remote))
        asyncio.run_coroutine_threadsafe(
            self._send(request, remote=remote), self._loop)

    def stop(self):
        logger.info("Stopping AsyncCommThread")
        self.running = False
