# from sins import NetworkAllocator, NetworkLoad
from network_allocator import NetworkAllocator
from network_load import NetworkLoad
from concurrent.futures import ThreadPoolExecutor as Executor
import logging
import signal
from time import sleep
from random import random
from itertools import dropwhile
import pandapower as pp
import numpy as np
import csv

from defs import Allocation

logger = logging.getLogger('ElectricalSimulation')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)

class ElectricalSimulator:
    """ Simulate a communicating policy allocator
    """
    def __init__(self):
        self.net = net
        self.loads = {}
        self.executor = Executor(max_workers=10)
        self.allocation_id = {}
        self.running = True
        self.allocator = None
        # handler = lambda signum, frame: self.stop()
        signal.signal(signal.SIGINT, self.handle_signal)

    def handle_signal(self, signum, frame):
        logger.info("Captured interrupt")
        if isinstance(self.allocator, NetworkAllocator):
            try:
                self.allocator.stop_network()
            except Exception as ex:
                raise ex
        elif self.running:
            logger.info("Allocator not initialized")           
        
        if self.running:
            self.stop()
        else:
            logger.info("Electrical Simulator not running")

    def stop(self):
        logger.info("Stopping ElectricalSimulator")
        self.running = False
        self.executor.shutdown()
        print("ThreadPoolExecutor finished shutdown")
        self.allocator = None


    def create_allocator(self):
        self.allocator = NetworkAllocator(local='127.0.0.1:5555')
        self.executor.submit(self.allocator.run)

    def create_network(self, net):
        assert net != None and hasattr(net, 'load') and len(net.load) > 0
        self.net = net
        for l in list(self.net.load.index):
            self.loads[l] = NetworkLoad(local='127.0.0.1:500{}'.format(l))
            self.allocation_id[l] = 0
            self.loads[l].curr_allocation = Allocation(0, self.net.load['p_kw'][l].item(), 0)
            self.executor.submit(self.loads[l].run)
    
    def connect_network(self):
        for l in self.loads:
            logger.info("---------------------------Connecting {}-------------------------".format(self.loads[l].nid))
            self.loads[l].schedule(action=self.loads[l].send_join,
                    args={'dst':self.allocator.local})
    
    def optimize_pf(self):
        if self.running:
            pp.runopp(self.net, verbose=True)
        else:
            logger.info("ElectricalSimulator not running")

    def broadcast(self):
        if not self.running:
            logger.info("ElectricalSimulator not running")
            return
        logger.info("Broadcasting OPF results")
        for l in self.loads:
            if self.net.load['controllable'][l].item() == True:
                print("Broadcasting to load {}".format(self.loads[l].local))
                allocation_value = self.net.res_load['p_kw'][l].item()
                allocation = Allocation(self.allocation_id[l], allocation_value, 0)
                self.allocation_id[l] += 1
                self.allocator.schedule(
                    action=self.allocator.send_allocation, 
                    args={'nid':self.loads[l].nid, 'allocation':allocation})

    def collect(self): 
        if not self.running:
            logger.info("ElectricalSimulator not running")
            return
        logger.info("Collecting network allocations")
        logger.info(self.allocator.nodes)
        for l in self.loads:
            try:
                v = self.allocator.nodes[self.loads[l].nid].value
                self.net.load['p_kw'][l] = v
            except KeyError as k:
                logger.error("node {} didn't join allocator yet".format(k))

net = pp.create_empty_network()
# create buses
bus = [
    pp.create_bus(net, vn_kv=220.),
    pp.create_bus(net, vn_kv=110.),
    pp.create_bus(net, vn_kv=110.),
    pp.create_bus(net, vn_kv=110.)
]
# create 220/110 kV transformer
pp.create_transformer(net, bus[0], bus[1], std_type="100 MVA 220/110 kV")

# create 110 kV lines
line = [
    pp.create_line(net, bus[1], bus[2], length_km=70., std_type='149-AL1/24-ST1A 110.0'),
    pp.create_line(net, bus[2], bus[3], length_km=50., std_type='149-AL1/24-ST1A 110.0'),
    pp.create_line(net, bus[3], bus[1], length_km=40., std_type='149-AL1/24-ST1A 110.0')
]

# create generators
eg = pp.create_ext_grid(
    net, bus[1], min_p_kw=-1e9, 
    max_p_kw=1e9
    )
gen = [
    pp.create_gen(
        net, bus[2], p_kw=-80 * 1e3, 
        min_p_kw=-80e3, max_p_kw=0, vm_pu=1.01, 
        controllable=True
    ),
    pp.create_gen(
        net, bus[3], p_kw=-100 * 1e3, 
        min_p_kw=-100e3, max_p_kw=0, vm_pu=1.01, 
        controllable=True
    )]

# create some generation costs
pp.create_polynomial_cost(
    net, 0, 'ext_grid', np.array([-1, 0])
)
pp.create_polynomial_cost(
    net, 0, 'gen', np.array([-1, 0])
)
pp.create_polynomial_cost(
    net, 1, 'gen', np.array([-1, 0])
)

# create loads
loads = [
    pp.create_load(net, bus[1], p_kw=70e3, min_p_kw=40e3, max_p_kw=70e3, min_q_kvar=0, max_q_kvar=0, controllable=True),
    pp.create_load(net, bus[1], p_kw=70e3, controllable=False),
    pp.create_load(net, bus[2], p_kw=10e3, controllable=False)
]

elec = ElectricalSimulator()
elec.create_network(net)
elec.create_allocator()
elec.connect_network()


# Allocation generators
## Random behavior
def random_alloc(load):
    assert isinstance(elec, ElectricalSimulator)
    while elec.running:
        print("************************************************************************************************")
        v = random() * 1.0e5
        allocation = Allocation(0, v, 0)
        event = load.schedule(action=load.allocation_handle, args={'allocation':allocation}, time=3)
        event.callbacks.append(lambda e: load.allocation_report())
        # load.schedule(action=load.allocation_report)
        sleep(1)

## Table read
def load_csv(load, file):
    assert isinstance(elec, ElectricalSimulator)
    # Data prepation
    loads = []
    with open(file, newline='') as csvfile:
        reader = csv.reader(csvfile, delimiter=',')
        for row in reader:
            if row[0] != 'timedelta' and float(row[1]) != 0 :
                loads.append([float(row[0]), float(row[1])*1e3])
        
        for i in range(0, len(loads)):
            loads[i][0] = i+1
    # Scheduling allocation
    while elec.running and len(loads) > 0:
        if load.running:
            v = loads.pop(0)
            allocation = Allocation(0, v[1], 0)
            event = load.schedule(action=load.allocation_handle, args={'allocation':allocation}, time=v[0])
            event.callbacks.append(lambda e: load.allocation_report(time=v[0]))
        else:
            logger.info("node {} stopped".format(load.nid))


## main loop
def opf_loop():
    assert isinstance(elec, ElectricalSimulator)
    while elec.running:
        sleep(5)
        elec.optimize_pf()
        logger.info('OPF loads result\n{}'.format(elec.net.res_load))
        logger.info('OPF generators result\n{}'.format(elec.net.res_gen))
        elec.broadcast()        
        sleep(5)
        elec.collect()
        logger.info('\n{}'.format(elec.net.load))

elec.executor.submit(opf_loop)
elec.executor.submit(random_alloc, elec.loads[1])
elec.executor.submit(load_csv, elec.loads[2], 'PV_Nelly_House_1.csv')