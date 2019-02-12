#!/usr/bin/env python
# -*- coding: utf-8 -*-

import linecache
import os
import random
import signal
import tracemalloc
from concurrent.futures import ThreadPoolExecutor as Executor
from copy import deepcopy
from queue import Empty, Full, Queue
from threading import Lock
from time import sleep, time
from typing import Dict

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp
import pandapower.networks as pn
import pandas as pd

from sens import Allocation, SmartGridSimulation


def display_top(snapshot, key_type='lineno', limit=10):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)

    print("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        # replace "/path/to/module/file.py" with "module/file.py"
        filename = os.sep.join(frame.filename.split(os.sep)[-2:])
        print("#%s: %s:%s: %.1f KiB"
              % (index, filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            print('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        print("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    print("Total allocated size: %.1f KiB" % (total / 1024))


def monitor_memory(N):
    tracemalloc.start()
    while i in range(N):
        tracemalloc.start()
        snapshot = tracemalloc.take_snapshot()
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('traceback')
        stat = top_stats[0]
        print("%s memory blocks: %.1f KiB" % (stat.count, stat.size / 1024))
        for line in stat.traceback.format():
            print(line)
        sleep(1.0)
    tracemalloc.stop()


# %%
allocations_queue = Queue()  # type:Queue
measure_queues = {}  # type: Dict
network_size = Queue()  # type:Queue
plot_values = Queue(100)  # type:Queue
optimal_values = Queue()  # type:Queue
lock = Lock()
## Create SmartGridSimulation environment
sim = SmartGridSimulation()


# %%
# generate sequential port numbers
def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port + 1


def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.put(src)


## Used localy to load and prepare data
def load_csv(file, columns=None):
    if columns is None:
        columns = list()
    import pandas as pd

    # Data prepation
    curves = pd.read_csv(file)
    filtered = curves.filter(items=columns).values.tolist()
    return filtered


## This is an example of how to schedule events from a generated timeseries
def generate_allocations(node, old_allocation):
    # Scheduling allocations
    try:
        new_allocation = Allocation(
            aid=0,
            p_value=old_allocation.p_value * (1 + random.uniform(-1e-1, 1e-1)),
            q_value=old_allocation.q_value * (1 + random.uniform(-1e-1, 1e-1)),
            duration=random.uniform(1, 60))
        return new_allocation
    except Exception as e:
        print(e)


def allocation_updated(allocation: Allocation, node_addr: str):
    ## We receive node_addr as "X.X.X.X:YYYY"
    ## ind also identifies the node in pandapawer loads list
    # print("received allocation update")
    allocations_queue.put([time(), node_addr, allocation.p_value, allocation.q_value])
    try:
        res = measure_queues[node_addr].get_nowait()
    except Empty:
        res = None
    return res


def create_nodes(net, remote):
    ## Create remote agents of type NetworkLoad
    nodes = []
    for i in range(len(net.load.index)):
        node = sim.create_node('load', '127.0.0.1:{}'.format(next(port)))
        node.run()
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure = allocation_updated
        node.joined_callback = joined_network
        node.generate_allocations = generate_allocations
        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst': '{}'.format(remote)})
    return nodes


## Handle ctrl-c interruptin
def shutdown(x, y):
    allocations_queue.put([0, 0, 0, 0])
    sim.stop()


signal.signal(signal.SIGINT, shutdown)

port = gen_port(5555)


def runpp(net):
    lock.acquire()
    net_copy = deepcopy(net)
    lock.release()

    while True:
        try:
            qsize = allocations_queue.qsize()
            # print("runpp: updating {} new allocations".format(qsize))
            for i in range(qsize):
                timestamp, name, p_kw, q_kw = allocations_queue.get()
                if timestamp == 0:
                    return
                net_copy.load.loc[net_copy.load['name'] == name, 'p_kw'] = p_kw
                net_copy.load.loc[net_copy.load['name'] == name, 'q_kw'] = q_kw
        except Exception as e:
            print(e)
        converged = True
        try:
            pp.runpp(net_copy, init_vm_pu='results')
            # print("Finished runpp")
            converged = True
        except Exception as e:
            print(e)
            converged = False

        # Updating voltage measures for clients and live_plot
        if converged:
            for node in measure_queues:
                bus_ind = net_copy.load['bus'][net.load['name'] == node].item()
                vm_pu = 0
                vm_pu = net_copy.res_bus['vm_pu'][bus_ind].item()
                try:
                    measure_queues[node].put_nowait(vm_pu)
                except Full:
                    measure_queues[node].get()
                    measure_queues[node].put(vm_pu)
                # print("\nVotage at bus {}: {}\n".format(bus_ind, vm_pu))
            try:
                for row in net_copy.res_bus.iterrows():
                    if (net_copy.load.loc[net_copy.load['bus'] == row[0]]['controllable'] == True).any():
                        plot_values.put_nowait([time(), row[0], row[1][0].item()])
            except Full:
                print("plot_values is full")
                plot_values.get()
                plot_values.put([time(), row[0], row[1][0].item()])
            except Exception as e:
                print(e)


def optimize_network(net):
    lock.acquire()
    net_copy = net
    lock.release()
    while True:
        pp.runopp(net_copy, verbose=False)
        try:
            c_loads = net_copy.load[net_copy.load['controllable'] == True]
        except Exception as e:
            print(e)

        print("optimizing {} nodes".format(len(c_loads.index)))
        for row in c_loads.iterrows():
            try:
                p = net_copy.res_load['p_kw'][row[0]].item()
                q = net_copy.res_load['q_kvar'][row[0]].item()
                name = row[1]['name']
            except Exception as e:
                print("Error in optimize network: {}".format(e))
            allocation = Allocation(0, p, q, random.uniform(10, 60))
            allocator.schedule(allocator.send_allocation, args={'nid': name, 'allocation': allocation})
        sleep(10)


# %%
def live_plot(loads):
    buses = pd.unique([net.load.loc[net.load['name'] == load, 'bus'].item() for load in loads])
    fig = plt.figure()
    ax = {}
    lines = {}
    i = 1
    for bus in buses:
        ax[bus] = plt.subplot(2, 2, i)
        lines[bus] = ax[bus].plot([], [])[0]
        i = i + 1

    def init():
        for bus, a in ax.items():
            a.set_title('voltage value (p.u.) - bus {}'.format(bus))
            # a.set_aspect('auto', 'box')

        for i in lines:
            lines[i].set_data([], [])

        return [line for _, line in lines.items()] + [a for _, ax in ax.items()]

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
                t[bus_id] = [x - initial_time for x in t[bus_id]]
                xmin, xmax = ax[bus_id].get_xlim()
                ymin, ymax = ax[bus_id].get_ylim()
                if len(lines[bus_id].get_ydata()) == 0:
                    ax[bus_id].set_xlim(max(t[bus_id]), 2 * max(t[bus_id]))
                    ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, max(v[bus_id]) + 0.005)
                    ax[bus_id].relim()
                    # artists.append(ax[bus_id].get_xaxis())
                    # artists.append(ax[bus_id].get_yaxis())
                if max(t[bus_id]) >= xmax:
                    ax[bus_id].set_xlim(xmin, max(t[bus_id]) + 1)
                    ax[bus_id].relim()
                if max(v[bus_id]) >= ymax - 0.005:
                    ax[bus_id].set_ylim(ymin, max(v[bus_id]) + 0.005)
                    ax[bus_id].relim()
                elif min(v[bus_id]) > ymin + 0.05:
                    ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, ymax)
                    ax[bus_id].relim()
                if min(v[bus_id]) <= ymin:
                    ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, ymax)
                    ax[bus_id].relim()

                xdata = np.append(lines[bus_id].get_xdata(), t[bus_id])
                ydata = np.append(lines[bus_id].get_ydata(), v[bus_id])
                lines[bus_id].set_data(xdata, ydata)

            artists.append(line for _, line in lines)

        except Exception as e:
            print("Exception when filling lines {}".format(e))
        return artists

    anim = animation.FuncAnimation(fig, animate, data_gen, init_func=init,
                                   interval=10, blit=False, repeat=False)
    try:
        plt.autoscale(True)
        plt.show()
    except Exception as e:
        print(e)


# %%
## Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
## Hit Agent's run, from here on scheduled events will be executed
## if local address is not set at initialiazion or before run, 
## an exception is raised
initial_time = time()
allocator.run()
# %%
## Create a corresponding multi-agent deployment to the pandapower network
net = pn.case6ww()
nodes = create_nodes(net, allocator.local)
# %%
print("waiting for Network ready: {}".format(len(nodes)))
while network_size.qsize() < len(nodes):
    continue
print("Network ready")
for node in nodes:
    allocation = Allocation(
        0,
        net.load.loc[net.load['name'] == node.local, 'p_kw'].item(),
        net.load.loc[net.load['name'] == node.local, 'q_kvar'].item(),
        1)
    node.schedule(node.handle_allocation, args={'allocation': allocation})

net.load['min_p_kw'] = None
net.load['min_q_kvar'] = None
net.load['max_p_kw'] = None
net.load['max_q_kvar'] = None
net.load['controllable'] = False

# c_loads = random.choices([node.local for node in nodes], k=3)
c_loads = ['127.0.0.1:5556', '127.0.0.1:5557', '127.0.0.1:5558']
for load in c_loads:
    net.load.loc[net.load['name'] == load, 'controllable'] = True
    net.load.loc[net.load['name'] == load, 'min_p_kw'] = -1 * net.load.loc[net.load['name'] == load, 'p_kw']
    net.load.loc[net.load['name'] == load, 'min_q_kvar'] = -1 * net.load.loc[net.load['name'] == load, 'q_kvar']
    net.load.loc[net.load['name'] == load, 'max_p_kw'] = net.load.loc[net.load['name'] == load, 'p_kw']
    net.load.loc[net.load['name'] == load, 'max_q_kvar'] = net.load.loc[net.load['name'] == load, 'q_kvar']


def plot_objs():
    import objgraph

    while not sim.shutdown:
        sleep(30)
        objgraph.show_growth(limit=3)
        try:
            objgraph.show_chain(
                objgraph.find_backref_chain(random.choice(objgraph.by_type('weakref')), objgraph.is_proper_module),
                filename='chain.png')
        except Exception as e:
            print(e)
        # obj = objgraph.by_type('list')[1000]
        # objgraph.show_backrefs(obj, max_depth=10)
        break


# %%
with Executor(max_workers=200) as executor:
    executor.submit(runpp, net)
    executor.submit(optimize_network, net)
    # executor.submit(plot_objs)
    live_plot(c_loads)
    # executor.submit(monitor_memory, 5)
