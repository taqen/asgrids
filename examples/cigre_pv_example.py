from queue import Queue, Full, Empty
from threading import Lock
from time import time, sleep
from sens import SmartGridSimulation, Allocation, live_plot, runpp, optimize_network_pi, optimize_network_opf
from signal import signal, SIGINT
import pandapower.networks as pn
import pandapower as pp
import pandas as pd
import matplotlib.animation as animation
import matplotlib.pyplot as plt
from copy import deepcopy
import numpy as np
from concurrent.futures import ThreadPoolExecutor as Executor
import argparse

addr_to_name: dict = {}
allocations_queue: Queue = Queue(1000)
measure_queues: dict = {}
network_size: Queue = Queue(1000)
plot_values: Queue = Queue(1000)
voltage_values: Queue = Queue(1000)
allocation_generators: dict = {}
lock: Lock = Lock()

parser = argparse.ArgumentParser(
    description='Realtime Time multi-agent simulation of CIGRE LV network')
parser.add_argument('--with_pv', type=bool,
                    help='with or without PV power production',
                    default=False)
parser.add_argument('--csv_file', type=str,
                    help='CSV database with loads timeseries',
                    default='../victor_scripts/cigre/curves.csv')
parser.add_argument('--json_file', type=str,
                    help='CSV database with loads timeseries',
                    default='../victor_scripts/cigre/cigre_network_lv.json')
parser.add_argument('--with_optimize', type=bool,
                    help='CSV database with loads timeseries',
                    default=False)
parser.add_argument('--with_plot', type=bool,
                    help='CSV database with loads timeseries',
                    default=True)

args = parser.parse_args()

with_pv = args.with_pv
CSV_FILE = args.csv_file
JSON_FILE = args.json_file
with_optimize = args.with_optimize
with_plot = args.with_plot

print("WITH PV: {}".format(with_pv))
print("WITH OPTIMIZE: {}".format(with_optimize))
print("WITH PLOT: {}".format(with_plot))
# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()

# Handle ctrl-c interruptin
def shutdown(x, y):
    print("Shutdown")
    allocations_queue.put([0, 0, 0, 0])
    sim.stop()


signal(SIGINT, shutdown)


def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port + 1


port = gen_port(5555)


def csv_generator(file, columns=None):
    curves = pd.read_csv(file)
    if columns is None:
        columns = []

    # Data preparation
    filtered = curves.filter(items=['timestamp']+columns)
    filtered['timestamp'] = filtered['timestamp'].diff(periods=-1).abs()
    return iter(filtered.values.tolist())


def generate_allocations(node, old_allocation, now=0):
    if node not in allocation_generators:
        allocation_generators[node] = \
            csv_generator(CSV_FILE,
                          columns=['%s_P' % addr_to_name[node],
                                   '%s_Q' % addr_to_name[node]])
    # print("generating allocation for %s"%addr_to_name[node])
    t, p, q = [10, 0, 0]
    if not ('PV' in addr_to_name[node] and with_pv is False):
        while True:
            t, p, q = next(allocation_generators[node])
            if t > now:
                break
    allocation = Allocation(0, p, q, t)
    return allocation


def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.put(src)


def allocation_updated(allocation: Allocation, node_addr: str):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    allocations_queue.put(
        [time(), node_addr, allocation.p_value, allocation.q_value])
    try:
        res = measure_queues[node_addr].get_nowait()
    except Empty:
        res = None
    return res

def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    voltage_values.put_nowait([node_addr, v])

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    nodes = list()
    for i in range(len(net.load.index)):
        node = sim.create_node('load', '127.0.0.1:{}'.format(next(port)))
        node.run()
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure = allocation_updated
        node.joined_callback = joined_network
        node.generate_allocations = generate_allocations
        addr_to_name[node.local] = net.load['name'][i]
        if 'PV' in net.load['name'][i]:
            net.load['controllable'][i] = True
            net.load['min_p_kw'][i] = -30  # 30kW max production for each PV
            net.load['max_p_kw'][i] = 0
            net.load['min_q_kvar'][i] = 0
            net.load['max_q_kvar'][i] = 0

        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst': '{}'.format(remote)})
    return nodes


allocator = sim.create_node(
    ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
initial_time = time()
allocator.run()

net = pp.from_json(JSON_FILE)
net.load['min_p_kw'] = None
net.load['min_q_kvar'] = None
net.load['max_p_kw'] = None
net.load['max_q_kvar'] = None
net.load['controllable'] = False

nodes = create_nodes(net, allocator.local)
c_buses = []
for row in net.bus.iterrows():
    if (net.load.loc[net.load['bus'] == row[0]]['controllable'] == True).any():
        c_buses.append(row[0])

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


with Executor(max_workers=200) as executor:
    try:
        net_copy = deepcopy(net)
        executor.submit(runpp, net_copy, allocations_queue, measure_queues, plot_values, with_plot=True, initial_time=initial_time)
        if with_optimize:
            net_copy = deepcopy(net)
            allocator.allocation_updated = allocator_measure_updated
            executor.submit(optimize_network_pi, net_copy, allocator, voltage_values)

    except Exception as e:
        print(e)
    if with_plot:
        live_plot(c_buses, plot_values)
