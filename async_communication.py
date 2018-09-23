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
    def __init__(self):

        self._target_address = None  # type:str
        self._receive_callback = None
        self._log = logging.getLogger(__name__)

        name = 'AsyncCommThread'

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

    async def _send(self, request, inproc_address = None, tcp_host = None, tcp_port = None):
        if self.cliSocket is None:
            self.cliSocket = self.context.socket(zmq.DEALER)
        else:
            self.poller.unregister(self.cliSocket)
            self.cliSocket.close()
            self.cliSocket = self.context.socket(zmq.DEALER)


        #identity = u'client'
        #self.cliSocket.identity = identity.encode('ascii')
        if inproc_address is not None:
            socket_address = inproc_address
        else:
            if not (tcp_host and tcp_port):
                msg = 'You must either use create socket with both tcp port and tcp_host' \
                      'either with inproc address.'
                self.executor.submit(logger.critical, msg)
                raise ValueError(msg)
            else:
                socket_address = 'tcp://{t}:{p}'.format(t=tcp_host, p=tcp_port)
                self.executor.submit(print, 'sending ' + request + ' to ' + socket_address)

        self.cliSocket.connect(socket_address)
        self.poller.register(self.cliSocket, zmq.POLLIN)

        reply = None
        retries = self.retries
        while retries > 0:
            self.executor.submit(print,'sending')
            await self.cliSocket.send_multipart([str(request).encode('ascii')])
            items = dict(await self.poller.poll(self.timeout))
            if items.get(self.cliSocket) == zmq.POLLIN:
                self.executor.submit(print, 'received ack')
                msg = await self.cliSocket.recv_multipart()
                reply = msg
                break
            else:
                self.executor.submit(print, 'client socket timeout')
                if retries:
                    self.executor.submit(print, 'retrying')
                    self.poller.unregister(self.cliSocket)
                    self.cliSocket.close()
                    self.cliSocket = self.context.socket(zmq.DEALER)
                    self.cliSocket.connect(socket_address)
                    self.poller.register(self.cliSocket, zmq.POLLIN)
                else:
                    break
                #retries -= 1

        #yield reply

    async def _run_server(self, callback=None):
        self.executor.submit(print, 'running server')
        while True:
            items = dict(await self.poller.poll(self.timeout))
            if self.srvSocket in items and items[self.srvSocket] == zmq.POLLIN:
                #ident, msg = self.srvSocket.recv_multipart()
                msg = await self.srvSocket.recv_multipart()
                self.executor.submit(print, 'server received', msg)
                await self.srvSocket.send_multipart(msg)
                self.executor.submit(callback, msg)


    def run_server(self,callback=None, tcp_port=None, inproc_address=None):
        if not (tcp_port or inproc_address):
            msg = 'At least TCP or INPROC must be used with ListeningThread.'
            self.executor.submit(logger.critical, msg)
            raise ValueError(msg)
        if tcp_port and inproc_address:
            msg = 'Use either TCP either INPROC with ListeningThread, not both.'
            self.executor.submit(logger.critical, msg)
            raise ValueError(msg)

        self.executor.submit(print,'Server listening on port {!r}.'.format(tcp_port))

        self.srvSocket = self.context.socket(zmq.ROUTER)
        if inproc_address:
            self.srvSocket.bind(inproc_address)
        elif tcp_port:
            self.srvSocket.bind('tcp://*:{}'.format(tcp_port))
        else:
            exit(1) #TODO: do not exit without cleaning up

        self.poller.register(self.srvSocket, zmq.POLLIN)

        asyncio.run_coroutine_threadsafe(
            self._run_server(callback=callback), self.loop)


    def send(self, request, inproc_address = None, tcp_host = None, tcp_port = None):
        asyncio.run_coroutine_threadsafe(
            self._send(request, inproc_address=inproc_address, tcp_host=tcp_host, tcp_port=tcp_port), self.loop)


    def stop(self):
        logger.debug('CommunicationAddress {!r}: stop thread.'.format(self.name))
        self.poller.unregister(self.cliSocket)
        self.poller.unregister(self.srvSocket)
        self.loop.stop()
        self.context.destroy()
        exit()

