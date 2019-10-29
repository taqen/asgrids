from queue import Queue, Full, Empty
from threading import Event, Lock
from time import monotonic as time, sleep
from asgrids import SmartGridSimulation, Allocation, Packet
from signal import signal, SIGINT
import pandapower.networks as pn
import pandapower as pp
import numpy as np
import pandas as pd
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor as Executor
import argparse
import logging
import functools
import sys

addr_to_name: dict = {}
allocations_queue: Queue = Queue()
measure_queues: dict = {}
network_size: list = []
network_ready: Queue = Queue(1)
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
                    default='./cigre_curves.csv')
parser.add_argument('--json-file', type=str,
                    help='CSV database with loads timeseries',
                    default='./cigre_network_lv.json')
parser.add_argument('--optimize', action='store_true',
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

logger = None

if output is not '':
    logger = logging.getLogger('SmartGridSimulationN')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(output, mode='w')
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)

print("WITH PV: {}".format(with_pv))
if with_optimize:
    print("WITH OPTIMIZER: {}".format(optimizer))
    print("WITH OPTIMIZE CYCLE: {}".format(optimize_cycle))
print("PP CYCLE: {}".format(pp_cycle))
print("SIM TIME: {}s".format(simtime))
print("INITIAL ADDRESS {}:{}".format(address, initial_port))
print("MAX VM_PU {}".format(max_vm))

terminate = Event()
terminate.clear()
# Handle ctrl-c interruption
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

def generate_allocations(node):
    initial_time = time()
    if node not in allocation_generators:
        allocation_generators[node] = \
            csv_generator(CSV_FILE,
                          columns=['%s_P' % addr_to_name[node],
                                   '%s_Q' % addr_to_name[node]])
    return allocation_generators[node]

def single_generate(node, old_allocation, now, name, initial_time, node_data):        
    real_now = time() - initial_time
    p, q, d = [0, 0, 1]
    if 'PV' in name:
        if with_pv:
            try:
                t, p, q, d = node_data.iloc[int(real_now)]
            except Exception as e:
                print(e)
                shutdown(0,0)
                pass
    else:
        try:
            t, p, q, d = node_data.iloc[int(real_now)]
        except Exception as e:
            print(e)
            pass
    return Allocation(0, p, q, 1)

def node_allocation_updated(allocation: Allocation, node_addr: str, timestamp):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    # print("Node %s updated allocation"%node_addr)
    try:
        allocations_queue.put(
            [time(), node_addr, allocation.p_value, allocation.q_value])
        measure = measure_queues[node_addr].get_nowait()
        # if logger is not None:
        #     logger.info('{}\t{}\t{}\t{}\t{}'.format(
        #         time(), addr_to_name[node_addr], allocation.p_value, allocation.q_value, measure))
        return measure
    except Empty:
        return None
    except Exception as e:
        print("Error in allocation_updated: {}".format(e))

# Collects received measures at allocator
def allocator_measure_updated(allocation: list, node_addr: str):
    # we receive a list containing current PQ values and Voltage measure
    # v = allocation[1]
    # print("allocator updated v = {} for node {}".format(v, node_addr))
    try:
        voltage_values.put_nowait([node_addr, allocation])
    except Full:
        print("voltage_values is full")

# Create SmartGridSimulation environment
sim: SmartGridSimulation = SmartGridSimulation()

REMOTES = {1:"10.10.10.144", 2:"10.10.10.45", 3:"10.10.10.88"}
# from pylxd import Client
# client = Client()
# for c in client.containers.all():
#     c.start()
# REMOTES=[c.state().network['eth0']['addresses'][0]['address'] for c in client.containers.all()]

def create_nodes(net, remote):
    # Create remote agents of type NetworkLoad
    for i in range(len(net.load.index)):
        node = None
        if i in REMOTES:
            node,_ = sim.create_remote_node(hostname=REMOTES[i], username='ubuntu', keyfile='~/.ssh/id_rsa.pub', ntype='load', addr='{}:{}'.format(address, next(port)))
        else:
            node = sim.create_node('load', '{}:{}'.format(address, next(port)))
        node.update_measure_period = 1
        node.report_measure_period = 1        
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure_cb = node_allocation_updated
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
        if i in REMOTES:
            ## 
            # What happens here is that, we try to reduce rpyc traffic, thus network latency that happens when remote nodes call local allocations generators
            # To do that, I first generate all the data needed for the remote node, and `deliver` it to where the node is.
            # Secondly, I `teleport` the `single_generate` function body, which will result in it being re-defined in the remote python context created by RPyC.
            # The remote single_generate will be hooked to the remote node's generate_allocations callback, so that no actual remote calls are made to get new allocations.

            node.curr_allocation = sim.deliver(node.____conn__, allocation)
            data = generate_allocations(node.local)
            # Can't deliver pandas DataFrames, data has to be convert to dict.
            node.____conn__.namespace['node_data'] = sim.deliver(node.____conn__, data.to_dict())
            node.____conn__.namespace['single_generate'] = sim.teleport(node.____conn__, single_generate)
            node.____conn__.execute("from time import monotonic as time")
            node.____conn__.execute("from functools import partial")
            node.____conn__.execute("from asgrids import Allocation")
            # recreating data as a DataFrame to be used inside `single_generate`
            node.____conn__.execute("import pandas as pd")
            node.____conn__.execute("node_data=pd.DataFrame(node_data)")
            try:
                node.____conn__.execute(f"partial_single_generate = partial(single_generate, name='{addr_to_name[node.local]}', initial_time=time(), node_data=node_data)")
                node.generate_allocations = node.____conn__.namespace['partial_single_generate']
            except Exception as e:
                print(e)

        else:
            node.curr_allocation = allocation
            node_data = generate_allocations(node.local)
            node.generate_allocations = functools.partial(single_generate, name=addr_to_name[node.local], initial_time=time(), node_data=node_data)
        nodes.append(node)
        
    return nodes


net = pp.from_json(JSON_FILE)
net.bus['min_vm_pu'] = 2 - max_vm
net.bus['max_vm_pu'] = max_vm
net.load['min_p_kw'] = None
net.load['min_q_kvar'] = None
net.load['max_p_kw'] = None
net.load['max_q_kvar'] = None
net.load['controllable'] = False


allocator = sim.create_node(
    ntype='allocator', addr="{}:{}".format(address, next(port)))
nodes = create_nodes(net, allocator.local)
allocator.allocation_updated = allocator_measure_updated
initial_time = sim.start()

def worker_pp(fn, args: list, cycle: float):
    import sys, traceback
    while not terminate.is_set():
        try:
            lock.acquire()
            fn(*args)
            lock.release()
        except Exception as e:
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
            print(e)
            break
        if cycle > 0:
            sleep(cycle)
    print("Terminating {}".format(fn))

allocator.schedule(shutdown, args=[None, None], delay=simtime)
with Executor(max_workers=200) as executor:
    try:
        print("Running power flow analysis")
        executor.submit(worker_pp, sim.runpp, [net, allocations_queue, measure_queues, initial_time, logger], pp_cycle)
        if with_optimize:
            if optimizer == 'pi':
                print("Optimizing network in realtime with PI")
                executor.submit(worker_optimize, sim.optimize_network_pi, [allocator, voltage_values, optimize_cycle, max_vm], optimize_cycle)
            elif optimizer == 'opf':
                print("Optimizing network in realtime with OPF")
                executor.submit(worker_optimize, sim.optimize_network_opf, [allocator, voltage_values, optimize_cycle, max_vm, opf_forecast, opf_check], optimize_cycle)
            else:
                raise ValueError("optimizer has to be either 'pi' or 'opf'")
    except Exception as e:
        print(e)