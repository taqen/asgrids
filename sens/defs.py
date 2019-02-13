#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
from collections import namedtuple
from queue import Queue
from random import Random
from typing import Callable
from matplotlib import pyplot as plt, animation
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
    def __new__(cls, aid=0, p_value=0, q_value=0, duration=0):
        return super(Allocation, cls).__new__(cls, aid, p_value, q_value, duration)

    def __eq__(self, y):
        return self.p_value == y.p_value and self.q_value == y.q_value and self.duration == y.duration


class Packet(namedtuple('Packet', ['ptype', 'payload', 'src', 'dst'])):
    def __new__(cls, ptype, payload=None, src=None, dst=None):
        if ptype not in packet_types:
            raise ValueError('Undefined packet type {}'.format(ptype))
        if ptype in ['allocation', 'curr_allocation']:
            assert isinstance(payload, Allocation), 'Packet type "allocation" needs an allocation payload not a ' \
                                                    '{}'.format(type(payload))
        return super(Packet, cls).__new__(cls, ptype, payload, src, dst)


def ext_pack(x):
    if isinstance(x, Packet):
        return msgpack.ExtType(1, msgpack.packb([x[0], x[1], x[2], x[3]], default=ext_pack, strict_types=True))
    elif isinstance(x, Allocation):
        return msgpack.ExtType(2, msgpack.packb([x[0], x[1], x[2], x[3]], default=ext_pack, strict_types=True))
    return x


def ext_unpack(code, data):
    if code == 1:
        ptype, payload, src, dst = msgpack.unpackb(data, ext_hook=ext_unpack, encoding='utf-8')
        return Packet(ptype, payload, src, dst)
    elif code == 2:
        aid, p_value, q_value, duration = msgpack.unpackb(data, ext_hook=ext_unpack, encoding='utf-8')
        return Allocation(aid, p_value, q_value, duration)


def EventId(p, nid=0) -> str:
    if isinstance(p, Allocation):
        assert isinstance(nid, str)
        eid = hashlib.md5('allocation {} {}'.format(p.aid, nid).encode()).hexdigest()
        return eid
    elif isinstance(p, Packet):
        if p.ptype == 'allocation' or p.ptype == 'allocation_ack':
            assert nid == 0
            eid = hashlib.md5('allocation {} {}'.format(p.payload.aid, p.src).encode()).hexdigest()
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
            raise ValueError('EventId not implemented for Packet type {}'.format(p.ptype))
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

def live_plot(buses, plot_values):
    fig = plt.figure()
    ax = {}
    lines = {}
    min_lines = {}
    max_lines = {}
    from math import ceil, sqrt
    grid_dim = ceil(sqrt(len(buses)))
    i = 1
    for bus in buses:
        ax[bus] = plt.subplot(grid_dim, grid_dim, i)
        lines[bus] = ax[bus].plot([], [])[0]
        min_lines[bus] = ax[bus].plot([], [], color='red')[0]
        max_lines[bus] = ax[bus].plot([], [], color='red')[0]
        i = i + 1
    plt.subplots_adjust(hspace=0.7, bottom=0.2)

    def init():
        try:
            for bus, a in ax.items():
                min_value = 0.95
                max_value = 1.05
                a.set_title('voltage value (p.u.) - bus {}'.format(bus))
                a.set_ylim([min_value*0.99, max_value*1.01])

                lines[bus].set_data([], [])
                min_lines[bus].set_data([0], [min_value])
                max_lines[bus].set_data([0], [max_value])
        except Exception as e:
            print("Error at live_plot init {}".format(e))

        artists = [line for _, line in lines.items()]
        artists = artists + [line for _, line in min_lines.items()]
        artists = artists + [line for _, line in max_lines.items()]
        artists = artists + [a for _, ax in ax.items()]

        return artists

    def data_gen():
        while True:
            timestamp = {}
            value = {}
            try:
                qsize = plot_values.qsize()
                for _ in range(qsize):
                    t, b, v = plot_values.get()
                    if b not in buses:
                        continue
                    else:
                        if b not in value:
                            timestamp[b] = []
                            value[b] = []
                        timestamp[b].append(t)
                        value[b].append(v)
            except Exception as e:
                print(e)
                raise e
            if timestamp == 0:
                break
            yield timestamp, value

    def animate(data):
        t, v = data
        artists = []
        try:
            for bus_id in v:
                xmin, xmax = ax[bus_id].get_xlim()
                ymin, ymax = ax[bus_id].get_ylim()
                if len(lines[bus_id].get_ydata()) == 0:
                    ax[bus_id].set_xlim(max(t[bus_id]), 2 * max(t[bus_id]))
                    # ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, max(v[bus_id]) + 0.005)
                    ax[bus_id].relim()
                if max(t[bus_id]) >= xmax:
                    ax[bus_id].set_xlim(xmin, max(t[bus_id]) + 1)
                    ax[bus_id].relim()
                if max(v[bus_id]) >= ymax:
                    ax[bus_id].set_ylim(ymin, max(v[bus_id]) + 0.005)
                    ax[bus_id].relim()
                # elif min(v[bus_id]) > ymin + 0.05:
                #     ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, ymax)
                #     ax[bus_id].relim()
                if min(v[bus_id]) <= ymin:
                    ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, ymax)
                    ax[bus_id].relim()

                xdata = np.append(lines[bus_id].get_xdata(), t[bus_id])
                ydata = np.append(lines[bus_id].get_ydata(), v[bus_id])
                if len(xdata) > 200:
                    xdata = xdata[100:]
                    ydata = ydata[100:]
                lines[bus_id].set_data(xdata, ydata)

                xdata = min_lines[bus_id].get_xdata()
                ydata = min_lines[bus_id].get_ydata()
                if len(xdata) > 200:
                    xdata = xdata[100:]
                    ydata = ydata[100:]
                    ax[bus_id].set_xlim(min(xdata), xmax)

                min_lines[bus_id].set_data(np.append(xdata, t[bus_id]), np.append(
                    ydata, [ydata[0]]*len(t[bus_id])))

                xdata = max_lines[bus_id].get_xdata()
                ydata = max_lines[bus_id].get_ydata()
                if len(xdata) > 200:
                    xdata = xdata[100:]
                    ydata = ydata[100:]
                max_lines[bus_id].set_data(np.append(xdata, t[bus_id]), np.append(
                    ydata, [ydata[0]]*len(t[bus_id])))

            artists = artists + [line for _, line in lines.items()]
            artists = artists + [line for _, line in max_lines.items()]
            artists = artists + [line for _, line in min_lines.items()]
            artists = artists + [a for _, a in ax.items()]
        except Exception as e:
            print("Exception when filling lines {}".format(e))
        return artists

    anim = animation.FuncAnimation(fig, animate, data_gen, init_func=init,
                                   interval=10, blit=False, repeat=False)
    try:
        plt.autoscale(True)
        plt.show()
    except Exception as e:
        print("Error at plt.show {}".format(e))
