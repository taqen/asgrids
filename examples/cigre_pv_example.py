from queue import Queue, Full, Empty
from threading import Lock
from time import time, sleep
from sens import SmartGridSimulation, Allocation, live_plot
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
allocations_queue: Queue = Queue()
measure_queues: dict = {}
network_size: Queue = Queue()
plot_values: Queue = Queue(1000)
optimal_values: Queue = Queue()
allocation_generators: dict = {}
lock: Lock = Lock()
CSV_FILE = '../victor_scripts/cigre/curves.csv'
with_pv = False

parser = argparse.ArgumentParser(
    description='Realtime Time multi-agent simulation of CIGRE LV network')
parser.add_argument('--with_pv', metavar='with_pv', type=bool,
                    help='with or without PV power production',
                    default=False)
parser.add_argument('--csv_file', metavar='CSV_FILE', type=str,
                    help='CSV database with loads timeseries',
                    default='../victor_scripts/cigre/curves.csv')
args = parser.parse_args()

with_pv = args.with_pv
CSV_FILE = args.csv_file

print("WITH PV: {}".format(with_pv))
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


def generate_allocations(node, old_allocation):
    if node not in allocation_generators:
        allocation_generators[node] = \
            csv_generator(CSV_FILE,
                          columns=['%s_P' % addr_to_name[node],
                                   '%s_Q' % addr_to_name[node]])
    # print("generating allocation for %s"%addr_to_name[node])
    if 'PV' in addr_to_name[node] and with_pv is False:
        t, p, q = [10, 0, 0]
    else:
        t, p, q = next(allocation_generators[node])
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
            net.load['min_p_kw'][i] = 30  # 30kW max production for each PV
            net.load['max_p_kw'][i] = 0
            net.load['min_q_kvar'][i] = 0
            net.load['max_q_kvar'][i] = 0

        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst': '{}'.format(remote)})
    return nodes


def runpp(initial_time=0):
    lock.acquire()
    net_copy = deepcopy(net)
    lock.release()

    while True:
        try:
            qsize = allocations_queue.qsize()
            # print("runpp: updating {} new allocations".format(qsize))
            for i in range(qsize):
                timestamp, name, p_kw, q_kw = allocations_queue.get()
                if timestamp == name == p_kw == q_kw == 0:
                    print("Terminating runpp")
                    return
                net_copy.load.loc[net_copy.load['name'] == name, 'p_kw'] = p_kw
                net_copy.load.loc[net_copy.load['name'] == name, 'q_kw'] = q_kw
        except Exception as e:
            print(e)
        converged = True
        try:
            pp.runpp(net_copy, init_vm_pu='results', verbose=True)
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
                        plot_values.put_nowait(
                            [time()-initial_time, row[0], row[1][0].item()])
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
    from sens import PIController
    controller = PIController()
    while True:
        try:
            c_loads = net_copy.load[net_copy.load['controllable'] == True]
        except Exception as e:
            print(e)
        voltages = []
        for b in c_loads['bus']:
            voltages = voltages + [net_copy.res_bus['vm_pu'][b]]
        _, pv_a = controller.generate_allocations([], c_loads[''])

        print("optimizing {} nodes".format(len(c_loads.index)))
        for row in c_loads.iterrows():
            try:
                p = net_copy.res_load['p_kw'][row[0]].item()
                q = net_copy.res_load['q_kvar'][row[0]].item()
                name = row[1]['name']
            except Exception as e:
                print("Error in optimize network: {}".format(e))
            allocation = Allocation(0, p, q, random.uniform(10, 60))
            allocator.schedule(allocator.send_allocation, args={
                               'nid': name, 'allocation': allocation})
        sleep(10)

allocator = sim.create_node(
    ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
initial_time = time()
allocator.run()

net = pp.from_json('../victor_scripts/cigre/cigre_network_lv.json')
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
        executor.submit(runpp, initial_time)
    except Exception as e:
        print(e)
    live_plot(c_buses, plot_values)
