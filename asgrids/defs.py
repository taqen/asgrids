#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
from collections import namedtuple
from queue import Queue
from random import Random
from typing import Callable
import numpy as np
import msgpack

packet_types = [
    'allocation',
    'curr_allocation',
    'join',
    'join_ack',
    'allocation_ack',
    'stop',
    'stop_ack',
    'leave',
    'leave_ack'
]


class Allocation(namedtuple('Allocation', ['aid', 'p_value', 'q_value', 'duration'])):
    __slots__: list = []
    def __eq__(s, o): return (s.p_value, s.q_value, s.duration) == (o.p_value, o.q_value, q.duration)
    def __lt__(s, o): return (s.p_value, s.q_value, s.duration) < (o.p_value, o.q_value, q.duration)
    def __le__(s, o): return (s.p_value, s.q_value, s.duration) <= (o.p_value, o.q_value, q.duration)
    def __gt__(s, o): return (s.p_value, s.q_value, s.duration) > (o.p_value, o.q_value, q.duration)
    def __ge__(s, o): return (s.p_value, s.q_value, s.duration) >= (o.p_value, o.q_value, q.duration)

    def __new__(cls, aid=0, p_value=0, q_value=0, duration=0):
        return super(Allocation, cls).__new__(cls, aid, p_value, q_value, duration)

class Packet(namedtuple('Packet', ['ptype', 'payload', 'src', 'dst'])):
    def __new__(cls, ptype, payload=None, src=None, dst=None):
        if ptype not in packet_types:
            raise ValueError('Undefined packet type {}'.format(ptype))
        if ptype is 'allocation':
            assert isinstance(payload, Allocation), 'Packet type "allocation" needs an allocation payload not a ' \
                                                    '{}'.format(type(payload))
        if ptype in ['curr_allocation', 'join']:
            assert isinstance(
                payload, list), 'Packet type "curr_allocation" needs a list containing current allocation and' \
                ' current measure {}'.format(type(payload))
        return super(Packet, cls).__new__(cls, ptype, payload, src, dst)


def ext_pack(x):
    if isinstance(x, Packet):
        return msgpack.ExtType(1, msgpack.packb([x[0], x[1], x[2], x[3]], default=ext_pack, strict_types=True))
    elif isinstance(x, Allocation):
        return msgpack.ExtType(2, msgpack.packb([x[0], x[1], x[2], x[3]], default=ext_pack, strict_types=True))
    return x


def ext_unpack(code, data):
    if code == 1:
        ptype, payload, src, dst = msgpack.unpackb(
            data, ext_hook=ext_unpack, encoding='utf-8')
        return Packet(ptype, payload, src, dst)
    elif code == 2:
        aid, p_value, q_value, duration = msgpack.unpackb(
            data, ext_hook=ext_unpack, encoding='utf-8')
        return Allocation(aid, p_value, q_value, duration)


def EventId(p, nid=0) -> str:
    if isinstance(p, Allocation):
        assert isinstance(nid, str)
        eid = hashlib.md5('allocation {} {}'.format(
            p.aid, nid).encode()).hexdigest()
        return eid
    elif isinstance(p, Packet):
        if p.ptype == 'allocation' or p.ptype == 'allocation_ack':
            assert nid == 0
            eid = hashlib.md5('allocation {} {}'.format(
                p.payload.aid, p.src).encode()).hexdigest()
            return eid
        elif p.ptype == 'stop_ack':
            assert nid == 0
            eid = hashlib.md5('stop {}'.format(p.src).encode()).hexdigest()
            return eid
        elif p.ptype == 'stop':
            assert isinstance(nid, str)
            eid = hashlib.md5('stop {}'.format(nid).encode()).hexdigest()
            return eid
        else:
            raise ValueError(
                'EventId not implemented for Packet type {}'.format(p.ptype))
    else:
        raise ValueError('EventId not implemented for {}'.format(p))


class AllocationGenerator(object):
    def __init__(self):
        self._random = Random()
        self._aid = 0  # type:int
        self._callback = None  # type:Callable

    def hook(self, callback: Callable):
        self._callback = callback

    def unhook(self):
        self._callback = None

    def get_allocation(self) -> Allocation:
        raise NotImplementedError


class MeasuresProvider(object):
    def __init__(self):
        self.current_measure = Queue(maxsize=1)

    def get_measure(self):
        return self.current_measure.get()
