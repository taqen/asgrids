#!/usr/bin/env python
# -*- coding: utf-8 -*-
import zmq
import threading
import asyncio
import zmq.asyncio
import logging
import _pickle as pickle

# Get the local logger
logger = logging.getLogger(__name__)


class AsyncCommunication(threading.Thread):
    def __init__(self, identity=None):

        self._target_address = None  # type:str
        self._receive_callback = None
        self._log = logging.getLogger(__name__)

        self.identity = identity

        self.context = None
        self.client = None
        self.server = None
        self.poller = None
        self.timeout = 1000
        self.retries = 10

        self.context = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.loop = asyncio.new_event_loop()
        # self.loop.set_debug(True)

        name = 'AsyncCommThread'
        if identity:
            name = name+identity

        super(AsyncCommunication, self).__init__(name=name)

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _send(self, request, remote=None):
        if self.client is None:
            print("creating client")
            self.client = self.context.socket(zmq.DEALER)
        else:
            print("client already created")
            self.poller.unregister(self.client)
            self.client.close()
            self.client = self.context.socket(zmq.DEALER)

        if self.identity is not None:
            print("identity is %s" % self.identity)
            identity = pickle.dumps(self.identity)
            try:
                self.client.setsockopt(zmq.IDENTITY, identity)
            except Exception:
                print("Error while setting socket identity")

        if not remote:
            msg = 'no socket_address provided'
            print(msg)
            raise ValueError(msg)

        socket_address = 'tcp://{}'.format(remote)

        print("Connecting to {}".format(socket_address))
        try:
            self.client.connect(socket_address)
            self.poller.register(self.client, zmq.POLLIN)
        except Exception:
            print("Error connecting client socket")

        print('sending {} to {}'.format(request, socket_address))
        await self.client.send_multipart([pickle.dumps(request)])

    async def _run_server(self, callback=None):
        self.poller.register(self.server, zmq.POLLIN)
        print('running server')
        while True:
            items = dict(await self.poller.poll(self.timeout))
            if self.server in items and items[self.server] == zmq.POLLIN:
                print("receiving at server")
                ident, msg = await self.server.recv_multipart()
                msg = pickle.loads(msg)
                ident = pickle.loads(ident).decode()
                print('server received {} from {}'.format(msg, ident))
                callback(data=msg, src=ident)
                #TODO respond after server receive
                # await self.server.send_multipart(msg)
            if self.client in items and items[self.client] == zmq.POLLIN:
                ident, msg = await self.client.recv_multipart()
                print('received ack at client socket')
                #TODO Should this be further handled?
                msg = pickle.loads(msg)
                ident = pickle.loads(ident)
                self.executor.submit(callback, data=msg, src=ident)

    def run_server(self, callback=None, local_address=None):
        if not (local_address):
            msg = 'At least TCP address must be used.'
            raise ValueError(msg)
        if self.identity is None:
            self.identity = local_address.encode()
        print('Server listening on address tcp://{}.'.format(local_address))

        self.server = self.context.socket(zmq.ROUTER)
        self.server.bind('tcp://{}'.format(local_address))

        asyncio.run_coroutine_threadsafe(
            self._run_server(callback=callback), self.loop)

    def send(self, request, remote=None):
        print("send {} to {}".format(request, remote))
        asyncio.run_coroutine_threadsafe(
            self._send(request, remote=remote), self.loop)

    def stop(self):
        self.poller.unregister(self.client)
        self.poller.unregister(self.server)
        self.loop.stop()
        self.context.destroy()

