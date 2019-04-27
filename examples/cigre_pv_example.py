from queue import Queue, Full, Empty
from threading import Lock
from time import monotonic as time, sleep
from sens import SmartGridSimulation, Allocation, live_plot_voltage, runpp, optimize_network_pi, optimize_network_opf
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
network_size: list = []
plot_values: Queue = Queue(1000)
voltage_values: Queue = Queue(1000)
allocation_generators: dict = {}
lock: Lock = Lock()

parser = argparse.ArgumentParser(
    description='Realtime Time multi-agent simulation of CIGRE LV network')
parser.add_argument('--with-pv', action='store_true',
                    help='with or without PV power production')
parser.add_argument('--csv-file', type=str,
                    help='CSV database with loads timeseries',
                    default='../victor_scripts/cigre/curves.csv')
parser.add_argument('--json-file', type=str,
                    help='CSV database with loads timeseries',
                    default='../victor_scripts/cigre/cigre_network_lv.json')
parser.add_argument('--optimize', action='store_true',
                    help='CSV database with loads timeseries')
parser.add_argument('--plot-voltage', action='store_true',
                    help='CSV database with loads timeseries')
parser.add_argument('--plot-load', action='store_true',
                    help='CSV database with loads timeseries')
parser.add_argument('--optimize-cycle', type=int,
                    help='CSV database with loads timeseries',
                    default=5)
parser.add_argument('--optimizer', type=str,
                    help='CSV database with loads timeseries',
                    default='pi')
parser.add_argument('--sim-time', type=float,
                    help='Total simulation time',
                    default=300)

args = parser.parse_args()

with_pv = args.with_pv
CSV_FILE = args.csv_file
JSON_FILE = args.json_file
with_optimize = args.optimize
plot_voltage = args.plot_voltage
plot_load = args.plot_load
optimize_cycle = args.optimize_cycle
optimizer = args.optimizer
simtime = args.sime_time

print("WITH PV: {}".format(with_pv))
if with_optimize:
    print("WITH OPTIMIZER: {}".format(optimizer))
    print("WITH OPTIMIZE CYCLE: {}".format(optimize_cycle))
print("WITH PLOT: {}".format(plot_voltage))
print("SIM TIME: {}".format(simtime))

# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()

# Handle ctrl-c interruptin
def shutdown(x, y):
    print("Shutdown")
    allocations_queue.put([0, 0, 0, 0])
    voltage_values.put([0,0])
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
    filtered['duration'] = filtered['timestamp'].diff(periods=-1).abs()
    return iter(filtered.values.tolist())


def generate_allocations(node, old_allocation, now=0):
    if node not in allocation_generators:
        allocation_generators[node] = \
            csv_generator(CSV_FILE,
                          columns=['%s_P' % addr_to_name[node],
                                   '%s_Q' % addr_to_name[node]])
    # print("generating allocation for %s"%addr_to_name[node])
    p, q, d = [0, 0, 10]
    if not ('PV' in addr_to_name[node] and with_pv is False):
        while True:
            t, p, q, d = next(allocation_generators[node])
            if t >= now:
                break
    allocation = Allocation(0, p, q, d)
    return allocation


def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.append(src)


def allocation_updated(allocation: Allocation, node_addr: str, timestamp=None):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    if not timestamp:
        print("ERROR, received update without timestamp")
    allocations_queue.put(
        [timestamp, node_addr, allocation.p_value, allocation.q_value])
    try:
        res = measure_queues[node_addr].get_nowait()
    except Empty:
        res = None
    return res

def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    try:
        voltage_values.put_nowait([node_addr, v])
    except Full:
        print("voltage_values is full")

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    nodes = list()
    for i in range(len(net.load.index)):
        node = sim.create_node('load', '127.0.0.1:{}'.format(next(port)))
        node.run()
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure_cb = allocation_updated
        node.joined_callback = joined_network
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
allocator.identity = allocator.local
allocator.run()

net = pp.from_json(JSON_FILE)
net.load['min_p_kw'] = None
net.load['min_q_kvar'] = None
net.load['max_p_kw'] = None
net.load['max_q_kvar'] = None
net.load['controllable'] = False

nodes = create_nodes(net, allocator.local)
print("waiting for {} nodes to join network".format(len(nodes)))
while len(set(network_size)) < len(nodes):
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



with Executor(max_workers=200) as executor:
    try:
        net_copy = deepcopy(net)
        executor.submit(runpp, net_copy, allocations_queue, measure_queues, plot_values, with_plot=plot_voltage, initial_time=initial_time, log=True)
        if with_optimize:
            net_copy = deepcopy(net)
            if optimizer == 'pi':
                allocator.allocation_updated = allocator_measure_updated
                executor.submit(optimize_network_pi, net_copy, allocator, voltage_values, duty_cycle=optimize_cycle)
            elif optimizer == 'opf':
                allocator.allocation_updated = allocator_measure_updated
                executor.submit(optimize_network_opf, net_copy, allocator, voltage_values, duty_cycle=optimize_cycle)
            else:
                raise ValueError("optimizer has to be either 'pi' or 'opf'")
        allocator.schedule(shutdown, args=[None, None], delay=simtime)
    except Exception as e:
        print(e)
    if plot_voltage:
        plot_buses = []
        for row in net.bus.iterrows():
            if (net.load.loc[net.load['bus'] == row[0]]['controllable'] == True).any():
                plot_buses.append(row[0])
        live_plot_voltage(plot_buses, plot_values, interval=10)
