import linecache
import os
import random
from signal import signal, SIGINT
import tracemalloc
from concurrent.futures import ThreadPoolExecutor as Executor
from copy import deepcopy
from queue import Queue, Full
from threading import Lock, Event
from time import sleep, time
from typing import Dict
import argparse
import numpy as np
import pandapower as pp
import pandapower.networks as pn
import pandas as pd
from sens import Allocation, SmartGridSimulation


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
parser.add_argument('--nodes',
                    help='opf cycle(s)',
                    default="all")
parser.add_argument('--monitor', action='store_true',
                    help='')
parser.add_argument('--optimize', action='store_true',
                    help='')
parser.add_argument('--pp', action='store_true',
                    help='')
parser.add_argument('--initial-port', type=int,
                    default=4000)
parser.add_argument('--skip-join', action='store_true')
parser.add_argument('--pp-cycle', type=int,
                    help='CSV database with loads timeseries',
                    default=1)

args = parser.parse_args()
case=args.case
simtime = args.simtime
cycle = args.opf_cycle
monitor = args.monitor
optimize = args.optimize
run_pp = args.pp
nNodes = args.nodes
initial_port = args.initial_port
skip_join = args.skip_join
pp_cycle = args.pp_cycle
nodes: list = []

print("------------------------------------\n\
        using network: {} with {} nodes\n\
        simulation time: {}s\n\
        initial port: {}\
        ".format(case, nNodes, simtime, initial_port))
print("------------------------------------")

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



def monitor_memory(cycle=1):
    from pympler import tracker, muppy, summary
    memory_tracker: tracker.SummaryTracker = tracker.SummaryTracker()
    while not terminate.is_set():
        # print(2)
        sleep(cycle)
        # print(3)
        memory_tracker.print_diff()
    # summary.print_(summary.summarize(muppy.get_objects()))



addr_to_name: dict = {}
allocations_queue: Queue = Queue(100)
measure_queues: dict = {}
network_size: list = []
network_ready: Queue = Queue(1)
voltage_values: Queue = Queue(100)
allocation_generators: dict = {}
lock = Lock()

# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()
# Handle ctrl-c interruptin
def shutdown(x, y):
    print("Shutdown")
    terminate.set()
    allocations_queue.put([0, 0, 0, 0])
    voltage_values.put([0,0])
    try:
        network_ready.put_nowait(1)
    except:
        pass
    sim.stop()

signal(SIGINT, shutdown)

def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port + 1

port = gen_port(initial_port)

def joined_network(src, dst):
    network_size.append(src)
    print("{} nodes joined network".format(len(network_size)))
    if len(network_size) == len(nodes):
        network_ready.put(1)


def allocation_updated(allocation: Allocation, node_addr: str, timestamp):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    try:
        allocations_queue.put_nowait(
            [timestamp, node_addr, allocation.p_value, allocation.q_value])
    except Full:
        # print("Error in allocation_updated(allocations_queue): {}".format(e))
        return None
    except Exception as e:
        print("Error in allocation_updated(allocations_queue): {}".format(e))
        return None
    try:
        measure = measure_queues[node_addr].get_nowait()
        return measure
    except Exception as e:
        return None

def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    try:
        voltage_values.put_nowait([node_addr, v])
    except Exception as e:
        # print("voltage_values is full: {}".format(e))
        pass

def add_more_nodes(net, N):
    maxN = len(net.load.index)
    for i in range(N//maxN):
        for j in range(maxN):
            try:
                params = dict(net.load.loc[j])
            except:
                print("Error")
            if 'name' in params.keys() and params['name'] != None:
                params['name'] = params['name']+'_{}'.format(j+i*maxN)
            try:
                pp.create_load(net, **params)
            except:
                print("Error")
   
    for i in range(N%maxN):
        params = dict(net.load.loc[i])
        if 'name' in params.keys() and params['name'] != None:
            params['name'] = params['name']+'_{}'.format(N//maxN)
        pp.create_load(net, **params)

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    # nodes = list()
    sim_nodes = len(net.load.index)
    if nNodes !='all' and int(nNodes) <= sim_nodes:
        sim_nodes = int(nNodes)
    elif nNodes !='all' and int(nNodes) > sim_nodes:
        print("adding %d nodes to pandapower net"%(int(nNodes) - sim_nodes))
        try:
            add_more_nodes(net, int(nNodes) - sim_nodes)
        except Exception as e:
            print(e)
        sim_nodes = int(nNodes)
    for i in range(sim_nodes):
        port_number=next(port)
        # print('load', '127.0.0.1:{}'.format(port_number))
        node = sim.create_node('load', '127.0.0.1:{}'.format(port_number))
        node.update_measure_period = 1
        node.run()
        measure_queues[node.local] = Queue(1)
        if run_pp:
            node.update_measure_cb = allocation_updated
        node.joined_callback = joined_network
        addr_to_name[node.local] = net.load['name'][i]
        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)
        allocation = Allocation(
            0,
            net.load.loc[net.load['name'] == node.local, 'p_kw'].item(),
            net.load.loc[net.load['name'] == node.local, 'q_kvar'].item(),
            1)
        node.curr_allocation = allocation

    if not skip_join:
        for node in nodes:
            allocator.send_join_ack(node.local)
            # node.schedule(node.send_join, {'dst': '{}'.format(remote)})
    return nodes

allocator = sim.create_node(
    ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
initial_time = time()
allocator.identity = allocator.local
if optimize:
    allocator.allocation_updated = allocator_measure_updated
allocator.run()

if case in cases.keys():
    net = cases[case]()
else:
    raise(ValueError("Wrong case"))

create_nodes(net, allocator.local)
print("Created nodes")

print("waiting for {} nodes to join network".format(len(nodes)))
network_ready.get()
print("Network ready")

for node in nodes:
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
            ARGS = [net] + args
            if (net.res_bus['vm_pu']>=1.05).all():
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
        if run_pp:
            print("Running power flow analysis")
            executor.submit(worker_pp, sim.runpp, [net, allocations_queue, measure_queues, initial_time, (True if pp_cycle is 0 else False), None], pp_cycle)
        if optimize:
            print("Optimizing network in realtime with OPF")
            executor.submit(worker_optimize, sim.optimize_network_opf, [allocator, cycle, 1.01], cycle)
        if monitor:
            monitor_memory(10)

    except Exception as e:
        print(e)

