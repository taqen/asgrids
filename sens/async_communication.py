#!/usr/bin/env python
# -*- coding: utf-8 -*-
import asyncio
import logging
import threading

import zmq
import zmq.asyncio
from concurrent.futures import ThreadPoolExecutor
import msgpack
from defs import ext_pack, ext_unpack

# Get the local logger
logger = logging.getLogger('AsyncCommThread')
# logger.setLevel(logging.DEBUG)
# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ch = logging.StreamHandler()
# ch.setLevel(logging.DEBUG)
# ch.setFormatter(formatter)
# logger.addHandler(ch)

class AsyncCommunication(threading.Thread):
    def __init__(self, local_address, callback=None, identity=None):

        self._target_address = None  # type:str
        self._receive_callback = None
        self._log = logging.getLogger(__name__)
        self.identity = identity
        self.callback = callback
        self.local_address = local_address
        self.context = None
        self.client = None
        self.server = None
        self.poller = None
        self.timeout = 1000
        self.running = False
        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.loop = asyncio.new_event_loop()
        self.loop.set_debug(False)
        self.executor = ThreadPoolExecutor(max_workers=10,
                                           thread_name_prefix='executor')
        self.loop.set_default_executor(self.executor)
        name = 'AsyncCommThread'
        if identity:
            name = name + identity

        threading.Thread.__init__(self, name=name)
        #super(AsyncCommunication, self).__init__(name=name)

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.running = True
        server_future = asyncio.ensure_future(
            self._run_server(callback=self.callback,
                             local_address=self.local_address),
            loop=self.loop)
        try:
            self.loop.run_until_complete(server_future)
        finally:
            self.loop.close()

    async def _send(self, request, remote=None):
        if self.client is None:
            logger.debug("creating client")
            self.client = self.context.socket(zmq.DEALER)
            # No lingering after socket is closed.
            # This has proven to cause problems terminating asyncio if not 0
            self.client.setsockopt(zmq.LINGER, 100)

        if self.identity is not None:
            logger.info("identity is %s" % self.identity)
            identity = msgpack.packb(self.identity, encoding='utf-8')
            try:
                self.client.setsockopt(zmq.IDENTITY, identity)
            except zmq.ZMQError as zmqerror:
                logger.error("Error setting socket identity. {}".format(zmqerror))

        if not remote:
            msg = 'no socket_address provided'
            raise ValueError(msg)

        socket_address = 'tcp://{}'.format(remote)

        logger.info("Connecting to {}".format(socket_address))
        try:
            self.client.connect(socket_address)
            self.poller.register(self.client, zmq.POLLIN)
        except zmq.ZMQError as zmqerror:
            logger.error("Error connecting client socket. {}".format(zmqerror))
            raise zmqerror

        try:
            p = msgpack.packb(request, default=ext_pack, strict_types=True, encoding='utf-8')
        except Exception as e:
            logger.error("Error packing {}".format(e))

        logger.info('sending {} to {}'.format(request, socket_address))
        await self.client.send_multipart([p])
        self.poller.unregister(self.client)
        self.client.close()
        self.client = None

    async def _run_server(self, local_address, callback=None):
        if not local_address:
            msg = 'At least TCP address must be used.'
            raise ValueError(msg)
        if self.identity is None:
            self.identity = local_address.encode()
        logger.debug('Server listening on address tcp://{}.'.format(local_address))

        self.server = self.context.socket(zmq.ROUTER)
        self.server.bind('tcp://{}'.format(local_address))
        self.poller.register(self.server, zmq.POLLIN)
        logger.info('running server')
        try:
            while self.running:
                items = dict(await self.poller.poll(self.timeout))
                if self.server in items and items[self.server] == zmq.POLLIN:
                    logger.debug("receiving at server")
                    ident, msg = await self.server.recv_multipart()
                    p = msgpack.unpackb(msg, ext_hook=ext_unpack, encoding='utf-8')
                    ident = msgpack.unpackb(ident, encoding='utf-8')
                    logger.debug('server received {} from {}'.format(p, ident))
                    await self.loop.run_in_executor(self.executor,
                                                    callback,
                                                    p,
                                                    ident)
        except KeyboardInterrupt:
            logger.debug("async_communication loop interrupted")
        finally:
            logger.info("stopping server")
            self.poller.unregister(self.server)
            self.server.close()

    def send(self, request, remote=None):
        logger.debug("send {} to {}".format(request, remote))
        asyncio.run_coroutine_threadsafe(
            self._send(request, remote=remote), self.loop)

    def stop(self):
        logger.info("Stopping AsyncCommThread")
        self.running = False
