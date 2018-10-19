#!/usr/bin/env python
# -*- coding: utf-8 -*-
import zmq
import threading
import asyncio
import zmq.asyncio
import concurrent.futures
import logging
import msgpack

from threading import Event as ThreadEvent

# Get the local logger
logger = logging.getLogger(__name__)

class AsyncCommunication(threading.Thread):
    def __init__(self, identity=None):

        self._target_address = None  # type:str
        self._receive_callback = None
        self._log = logging.getLogger(__name__)

        name = 'AsyncCommThread'
        self.identity=identity
        if identity:
            name = name+identity

        self.context = None
        self.cliSocket = None
        self.srvSocket = None
        self.poller = None
        self.timeout = 1000
        self.retries = 10

        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.loop = asyncio.new_event_loop()
        self.loop.set_debug(True)

        self.executor = self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        super(AsyncCommunication, self).__init__(name=name)

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _send(self, request, remote = None):
        if self.cliSocket is None:
            self.cliSocket = self.context.socket(zmq.DEALER)
        else:
            self.poller.unregister(self.cliSocket)
            self.cliSocket.close()
            self.cliSocket = self.context.socket(zmq.DEALER)

        if self.identity is not None:
            self.cliSocket.setsockopt(zmq.IDENTITY, msgpack.packb(self.identity))
        if not remote:
            msg = 'no socket_address provided'
            self.executor.submit(print, msg)
            raise ValueError(msg)
        else:
            socket_address = 'tcp://{}'.format(remote)
            self.executor.submit(print, 'sending ' + request + ' to ' + socket_address)

        self.cliSocket.connect(socket_address)
        self.poller.register(self.cliSocket, zmq.POLLIN)

        self.executor.submit(print,'sending')
        await self.cliSocket.send_multipart(msgpack.packb(request))

    async def _run_server(self, callback=None):
        self.executor.submit(print, 'running server')
        while True:
            items = dict(await self.poller.poll(self.timeout))
            if self.srvSocket in items and items[self.srvSocket] == zmq.POLLIN:
                ident, msg = await self.srvSocket.recv_multipart()
                msg = msgpack.unpackb(msg, encoding='utf-8')
                ident = msgpack.unpackb(ident, encoding='utf-8')
                self.executor.submit(print, 'server received {} from {}'.format(msg, ident))
                self.executor.submit(callback, data=msg, src=ident)
                #TODO respond after server receive
                # await self.srvSocket.send_multipart(msg)
            if self.cliSocket in items and items[self.cliSocket] == zmq.POLLIN:
                ident, msg = await self.cliSocket.recv_multipart()
                self.executor.submit(print, 'received ack at client socket')
                #TODO Should this be further handled?
                msg = msgpack.unpackb(msg, encoding='utf-8')
                ident = msgpack.unpackb(ident, encoding='utf-8')
                self.executor.submit(callback, data=msg, src=ident)

    def run_server(self,callback=None, local_address=None):
        if not (local_address):
            msg = 'At least TCP address must be used.'
            self.executor.submit(logger.critical, msg)
            raise ValueError(msg)
        if self.identity is None:
            self.identity = local_address.encode()
        self.executor.submit(print,'Server listening on address tcp://{}.'.format(local_address))

        self.srvSocket = self.context.socket(zmq.ROUTER)
        self.srvSocket.bind('tcp://{}'.format(local_address))

        self.poller.register(self.srvSocket, zmq.POLLIN)

        asyncio.run_coroutine_threadsafe(
            self._run_server(callback=callback), self.loop)


    def send(self, request, remote = None):
        asyncio.run_coroutine_threadsafe(
            self._send(request, remote=remote), self.loop)


    def stop(self):
        logger.debug('CommunicationAddress {!r}: stop thread.'.format(self.name))
        self.poller.unregister(self.cliSocket)
        self.poller.unregister(self.srvSocket)
        self.loop.stop()
        self.context.destroy()
        exit()

