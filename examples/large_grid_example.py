import linecache
import os
import random
from signal import signal, SIGINT
import tracemalloc
from concurrent.futures import ThreadPoolExecutor as Executor
from copy import deepcopy
from collections import deque as Queue
from threading import Lock, Event
from time import sleep, time
from typing import Dict
import argparse

import numpy as np
import pandapower as pp
import pandapower.networks as pn
import pandas as pd
from sens import Allocation, SmartGridSimulation, optimize_network_opf, runpp
parser = argparse.ArgumentParser(
    description='Realtime Time multi-agent simulation of large smartgrid networks')
parser.add_argument('--case', type=str,
                    help='case scenario, one of: case6ww, \
                        case9,case14,case30,case_ieee30, \
                        case33bw,case39,case57,case118,case300',
                    default='case6ww')
parser.add_argument('--simtime', type=float,
                    help='simulation time',
                    default=30)
parser.add_argument('--opf-cycle', type=float,
                    help='opf cycle(s)',
                    default=6)
parser.add_argument('--monitor', action='store_true',
                    help='')
parser.add_argument('--optimize', action='store_true',
                    help='')
parser.add_argument('--pp', action='store_true',
                    help='')

args = parser.parse_args()
case=args.case
simtime = args.simtime
cycle = args.opf_cycle
monitor = args.monitor
optimize = args.optimize
pp = args.pp

if monitor:
    tracemalloc.start()

terminate = Event()
terminate.clear()

cases = {"case6ww": pn.case6ww,
         "case9": pn.case9,
         "case14": pn.case14,
         "case30": pn.case30,
         "case_ieee30": pn.case_ieee30,
         "case33bw": pn.case33bw,
         "case39": pn.case39,
         "case57": pn.case57,
         "case118": pn.case118,
         "case300": pn.case300
         }

def generate_allocations(node, old_allocation, now=0):
    # Scheduling allocations
    try:
        new_allocation = Allocation(
            aid=0,
            p_value=old_allocation.p_value * (1 + random.uniform(-1e-1, 1e-1)),
            q_value=old_allocation.q_value * (1 + random.uniform(-1e-1, 1e-1)),
            duration=random.uniform(20, 60))
        return new_allocation
    except Exception as e:
        print(e)



def display_top(snapshot, key_type='lineno', limit=10):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)
    trace_stats = snapshot.statistics('traceback')[:1]
    print("_-------------------------------------------------------------")
    print(trace_stats)
    print("---------------------------------------------------------------")
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


def monitor_memory():
    snapshot1 = tracemalloc.take_snapshot()
    try:
        snapshot1 = snapshot1.filter_traces((tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),tracemalloc.Filter(False, "<unknown>"),))
    except Exception as e:
        print(e)
        return
    sleep(10.0)

    try:
        while not False: #terminate.is_set():
            snapshot2 = tracemalloc.take_snapshot()
            snapshot2 = snapshot2.filter_traces(
                (tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
                tracemalloc.Filter(False, "<unknown>"),tracemalloc.Filter(False, tracemalloc.__file__),))

            # display_top(snapshot)
            top_stats = snapshot2.compare_to(snapshot1, 'lineno')
            snapshot1 = snapshot2
            print("[ Top 10 differences ]")
            for stat in top_stats[:10]:
                print(stat)
            sleep(10.0)
    except Exception as e:
        print(e)

def print_memory(frames):
    # Store 25 frames
    try:
        # ... run your application ...

        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('traceback')

        # pick the biggest memory block
        stat = top_stats[0]
        print("%s memory blocks: %.1f KiB" % (stat.count, stat.size / 1024))
        for line in stat.traceback.format():
            print(line)
    except Exception as e:
        print(e)


addr_to_name: dict = {}
allocations_queue: Queue = Queue(maxlen=1000)
measure_queues: dict = {}
network_size: list = []
voltage_values: Queue = Queue(maxlen=1000)
allocation_generators: dict = {}
lock = Lock()

# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()
# Handle ctrl-c interruptin
def shutdown(x, y):
    print("Shutdown")
    terminate.set()
    allocations_queue.append([0, 0, 0, 0])
    voltage_values.append([0,0])
    sim.stop()
    tracemalloc.stop()

signal(SIGINT, shutdown)

def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port + 1

port = gen_port(5000)

def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.append(src)


def allocation_updated(allocation: Allocation, node_addr: str, timestamp):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    try:
        allocations_queue.append(
            [timestamp, node_addr, allocation.p_value, allocation.q_value])
    except Exception as e:
        print("Error in allocation_updated(allocations_queue): {}".format(e))
        return None
    try:
        measure = measure_queues[node_addr].popleft()
        return measure
    except Exception as e:
        return None

def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    try:
        voltage_values.append([node_addr, v])
    except:
        print("voltage_values is full")

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    nodes = list()
    for i in range(len(net.load.index)):
        print('load', '127.0.0.1:{}'.format(next(port)))
        node = sim.create_node('load', '127.0.0.1:{}'.format(next(port)))
        node.update_measure_period = 1
        node.run()
        measure_queues[node.local] = Queue(maxlen=1)
        node.update_measure_cb = allocation_updated
        node.joined_callback = joined_network
        addr_to_name[node.local] = net.load['name'][i]
        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst': '{}'.format(remote)})
    return nodes


allocator = sim.create_node(
    ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
initial_time = time()
allocator.identity = allocator.local
allocator.allocation_updated = allocator_measure_updated
allocator.run()

if case in cases.keys():
    net = cases[case]()
else:
    raise(ValueError("Wrong case"))

nodes = create_nodes(net, allocator.local)
print("waiting for {} nodes to join network".format(len(nodes)))
while len(set(network_size)) < len(nodes) and not terminate.is_set():
    sleep(1)
    continue
print("Network ready")

for node in nodes:
    allocation = Allocation(
        0,
        net.load.loc[net.load['name'] == node.local, 'p_kw'].item(),
        net.load.loc[net.load['name'] == node.local, 'q_kvar'].item(),
        1)
    node.curr_allocation = allocation
    node.generate_allocations = generate_allocations


def worker_pp(fn, args: list, cycle: float):
    import sys, traceback
    while not terminate.is_set():
        try:
            lock.acquire()
            fn(*args)
            lock.release()
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("What the fuck at worker_pp:")
            print(repr(traceback.format_tb(exc_traceback)))
            return
        if cycle > 0:
            sleep(cycle)

def worker_optimize(fn, args: list, cycle: float):
    import sys, traceback
    while not terminate.is_set():
        try:
            lock.acquire()
            # netcopy = deepcopy(net)
            # lock.release()
            ARGS = [net] + args
            fn(*ARGS)
            lock.release()

        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("What the fuck at {}:".format(fn))
            print(repr(traceback.format_tb(exc_traceback)))
            break
        if cycle > 0:
            sleep(cycle)
    print("Terminating {}".format(fn))

allocator.schedule(shutdown, args=[None, None], delay=simtime)
with Executor(max_workers=200) as executor:
    try:
        if pp:
            print("Running power flow analysis")
            executor.submit(worker_pp, runpp, [net, allocations_queue, measure_queues, False, None, initial_time, None], 0)
        if optimize:
            print("Optimizing network in realtime with OPF")
            executor.submit(worker_optimize, optimize_network_opf, [allocator, voltage_values, cycle], cycle)
        # executor.submit(plot_objs)
        if monitor:
            executor.submit(monitor_memory)
        # executor.submit(print_memory, 25)

    except Exception as e:
        print(e)

