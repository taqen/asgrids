from queue import Queue, Full, Empty
from threading import Lock
from time import time, sleep
from sens import SmartGridSimulation, Allocation
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


def runpp():
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
                            [time(), row[0], row[1][0].item()])
            except Full:
                print("plot_values is full")
                plot_values.get()
                plot_values.put([time(), row[0], row[1][0].item()])
            except Exception as e:
                print(e)


def live_plot(buses):
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
                t[bus_id] = [x - initial_time for x in t[bus_id]]
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
        executor.submit(runpp)
    except Exception as e:
        print(e)
    live_plot(c_buses)
