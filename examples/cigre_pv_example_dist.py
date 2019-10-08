from queue import Queue, Full, Empty
from threading import Event, Lock
from time import monotonic as time, sleep
from asgrids import SmartGridSimulation, Allocation, Packet#, runpp, optimize_network_pi, optimize_network_opf#, live_plot_voltage
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
import logging

addr_to_name: dict = {}
allocations_queue: Queue = Queue()
measure_queues: dict = {}
network_size: list = []
network_ready: Queue = Queue(1)
plot_values: Queue = Queue()
voltage_values: Queue = Queue()
allocation_generators: dict = {}
lock = Lock()
initial_time = None
nodes: list = []

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
parser.add_argument('--pp-cycle', type=int,
                    help='CSV database with loads timeseries',
                    default=0)
parser.add_argument('--optimizer', type=str,
                    help='OPF or PI',
                    default='pi')
parser.add_argument('--sim-time', type=float,
                    help='Total simulation time',
                    default=300)
parser.add_argument('--output', type=str,
                    help='Total simulation time',
                    default='simulation.log')
parser.add_argument('--initial-port', type=int,
                    help='Initial network port',
                    default=4000)
parser.add_argument('--address', type=str,
                    help='network address',
                    default="127.0.0.1")
parser.add_argument('--skip-join', action="store_true",
                    help='skip waiting for join')
parser.add_argument('--max-vm', type=float,
                    help='maxium voltage that triggers optimization',
                    default=1.01)
parser.add_argument('--accel', type=float,
                    help='maxium voltage that triggers optimization',
                    default=1.0)
parser.add_argument('--p-factor', type=float,
                    default=1.0)
parser.add_argument('--no-forecast', action='store_true')
parser.add_argument('--check-limit', action='store_true')
args = parser.parse_args()
opf_forecast = not args.no_forecast
opf_check = args.check_limit
p_factor = args.p_factor
accel=args.accel
assert accel > 0
max_vm = args.max_vm
skip_join = args.skip_join
with_pv = args.with_pv
CSV_FILE = args.csv_file
JSON_FILE = args.json_file
with_optimize = args.optimize
plot_voltage = args.plot_voltage
plot_load = args.plot_load
optimize_cycle = args.optimize_cycle
pp_cycle = args.pp_cycle
optimizer = args.optimizer
simtime = args.sim_time
output = args.output
initial_port = args.initial_port
address = args.address

curves = pd.read_csv(CSV_FILE)
curves.drop(curves[curves['timestamp']<=49].index, inplace=True)
curves.drop(curves[curves['timestamp']>=249].index, inplace=True)
curves.reset_index(drop=True, inplace=True)
curves['timestamp'] = curves['timestamp'] - curves.iloc[0, 0]

# logger_a will log all allocations and measurements received by the allocator
# logger_b will log all allocations and measurements known by each node
# logger_a = None
logger_n = None

if output is not '':
    # logger_a = logging.getLogger('SmartGridSimulationA')
    # logger_a.setLevel(logging.INFO)
    logger_n = logging.getLogger('SmartGridSimulationN')
    logger_n.setLevel(logging.INFO)
    # fh_a = logging.FileHandler(output.split('log')[0] +'a.log', mode='w')
    # fh_a.setLevel(logging.INFO)
    fh_n = logging.FileHandler(output, mode='w')
    fh_n.setLevel(logging.INFO)
    # logger_a.addHandler(fh_a)
    logger_n.addHandler(fh_n)

print("WITH PV: {}".format(with_pv))
if with_optimize:
    print("WITH OPTIMIZER: {}".format(optimizer))
    print("WITH OPTIMIZE CYCLE: {}".format(optimize_cycle))
print("PP CYCLE: {}".format(pp_cycle))
print("WITH PLOT: {}".format(plot_voltage))
print("SIM TIME: {}s".format(simtime))
print("INITIAL ADDRESS {}:{}".format(address, initial_port))
print("MAX VM_PU {}".format(max_vm))

# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()
terminate = Event()
terminate.clear()
# Handle ctrl-c interruptin
def shutdown(x, y):
    print("Shutdown")
    terminate.set()
    # allocations_queue.put([0, 0, 0, 0])
    # voltage_values.put([0,0])
    sim.stop()



signal(SIGINT, shutdown)


def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port + 1


port = gen_port(initial_port)


def csv_generator(file, columns=None):
    if columns is None:
        columns = []
    # Data preparation
    filtered = curves.filter(items=['timestamp']+columns)
    filtered['duration'] = filtered['timestamp'].diff(periods=-1).abs()
    return filtered


def generate_allocations(node, old_allocation, now=0):
    real_now = time() - initial_time
    if node not in allocation_generators:
        allocation_generators[node] = \
            csv_generator(CSV_FILE,
                          columns=['%s_P' % addr_to_name[node],
                                   '%s_Q' % addr_to_name[node]])
    # print("generating allocation for %s"%addr_to_name[node])
    p, q, d = [0, 0, 1*accel]
    if 'PV' in addr_to_name[node]:
        if with_pv:
            try:
                agen = allocation_generators[node]
                agen = agen.iloc[int(real_now)]
                t, p, q, d = agen
            except Exception as e:
                print(e)
                shutdown(0,0)
                pass
    else:
        try:
            t, p, q, d = allocation_generators[node][allocation_generators[node][0]>=real_now][0]
        except Exception as e:
            pass
    allocation = Allocation(0, p*p_factor, q, 1)
    return allocation


def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.append(src)
    if len(network_size) == len(nodes) and len(nodes) != 0:
        network_ready.put(1)


def allocation_updated(allocation: Allocation, node_addr: str, timestamp):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    try:
        allocations_queue.put(
            [timestamp, node_addr, allocation.p_value, allocation.q_value])
        measure = measure_queues[node_addr].get_nowait()
        # if logger_n is not None:
        #     logger_n.info('{}\t{}\t{}\t{}\t{}'.format(
        #         time(), addr_to_name[node_addr], allocation.p_value, allocation.q_value, measure))
        return measure
    except Empty:
        return None
    except Exception as e:
        print("Error in allocation_updated: {}".format(e))

# Collects allocator's received measures
def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    # v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    try:
        voltage_values.put_nowait([node_addr, allocation])
    except Full:
        print("voltage_values is full")
    # if logger_a is not None:
    #     logger_a.info('{}\t{}\t{}\t{}\t{}'.format(
    #         time(), addr_to_name[node_addr], allocation[0].p_value, allocation[0].q_value, v))

# REMOTES = {0:"10.10.10.119", 1:"10.10.10.228", 2:"10.10.10.10"}
from pylxd import Client
client = Client()
for c in client.containers.all():
    c.start()
REMOTES=[c.state().network['eth0']['addresses'][0]['address'] for c in client.containers.all()]

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    for i in range(len(net.load.index)):
        node = None
        if i < len(REMOTES):
            node,_ = sim.create_remote_node(hostname=REMOTES[i], username='ubuntu', keyfile='~/.ssh/id_rsa.pub', ntype='load', addr='{}:{}'.format(address, next(port)))
        else:
            node = sim.create_node('load', '{}:{}'.format(address, next(port)))
        node.update_measure_period = 1
        node.report_measure_period = 1        
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
            pp.create_polynomial_cost(net, i, 'load', np.array([1, 0]))

        net.load['name'][i] = "{}".format(node.local)        
        allocation = Allocation(
            0,
            net.load.loc[net.load['name'] == node.local, 'p_kw'].item(),
            net.load.loc[net.load['name'] == node.local, 'q_kvar'].item(),
            1)
        if i < len(REMOTES):
            node.curr_allocation = sim.deliver(allocation)
            node.generate_allocations = sim.teleport(generate_allocations)
        else:
            node.curr_allocation = allocation
            node.generate_allocations = generate_allocations
        nodes.append(node)
        
    for node in nodes:
        node.run()
        packet = Packet('join_ack', src=allocator.local, dst=node.local)
        node.handle_receive(packet)
    return nodes


allocator = sim.create_node(
    ntype='allocator', addr="{}:{}".format(address, next(port)))
allocator.identity = allocator.local
allocator.run()

net = pp.from_json(JSON_FILE)
net.bus['min_vm_pu'] = 2 - max_vm
net.bus['max_vm_pu'] = max_vm
net.load['min_p_kw'] = None
net.load['min_q_kvar'] = None
net.load['max_p_kw'] = None
net.load['max_q_kvar'] = None
net.load['controllable'] = False


nodes = create_nodes(net, allocator.local)
if not skip_join:
    print("waiting for {} nodes to join network".format(len(nodes)))
    network_ready.get()
print("Network ready")
initial_time = time()
allocator.allocation_updated = allocator_measure_updated

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
            print(e)
            return
        if cycle > 0:
            sleep(cycle)

def worker_optimize(fn, args: list, cycle: float):
    import sys, traceback
    while not terminate.is_set():
        lock.acquire()
        netcopy = deepcopy(net)
        lock.release()
        ARGS = [netcopy] + args
        try:
            fn(*ARGS)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("What the fuck at {}:".format(fn))
            print(repr(traceback.format_tb(exc_traceback)))
            break
        if cycle > 0:
            sleep(cycle)
    print("Terminating {}".format(fn))

allocator.schedule(shutdown, args=[None, None], delay=simtime*accel)
with Executor(max_workers=200) as executor:
    try:
        # net_copy = deepcopy(net)
        print("Running power flow analysis")
        executor.submit(worker_pp, sim.runpp, [net, allocations_queue, measure_queues, plot_values, plot_voltage, initial_time, logger_n], pp_cycle*accel)
        if with_optimize:
            # net_copy = deepcopy(net)
            if optimizer == 'pi':
                print("Optimizing network in realtime with PI")
                executor.submit(worker_optimize, sim.optimize_network_pi, [allocator, voltage_values, optimize_cycle*accel, max_vm], optimize_cycle*accel)
            elif optimizer == 'opf':
                print("Optimizing network in realtime with OPF")
                executor.submit(worker_optimize, sim.optimize_network_opf, [allocator, voltage_values, optimize_cycle*accel, max_vm, opf_forecast, opf_check], optimize_cycle*accel)
            else:
                raise ValueError("optimizer has to be either 'pi' or 'opf'")

    except Exception as e:
        print(e)
    # if plot_voltage:
    #     plot_buses = []
    #     for row in net.bus.iterrows():
    #         if (net.load.loc[net.load['bus'] == row[0]]['controllable'] == True).any():
    #             plot_buses.append(row[0])
    #     live_plot_voltage(plot_buses, plot_values, interval=10)
