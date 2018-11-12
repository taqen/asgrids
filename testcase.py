from sins import NetworkAllocator, NetworkLoad
from concurrent.futures import ThreadPoolExecutor
import signal
from time import sleep
from random import random
from itertools import dropwhile
import pandapower as pp
import numpy as np
import csv

class ElectricalSimulator:
    """ Simulate a communicating policy allocator
    """
    def __init__(self, net=None):
        self.net = net
        if net is None:
            self.net = pp.create_empty_network()
        self.loads = {}
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.allocation_id = {}

    def optimize_pf(self):
        pp.runopp(self.net, verbose=True)
    
    def create_allocator(self):
        self.allocator = NetworkAllocator(local='127.0.0.1:5555')
        handler = lambda signum, frame: self.stop()
        signal.signal(signal.SIGINT, handler)
        self.executor.submit(self.allocator.run)

    def add_loads(self, loads: list):
        # Create associated NetworkLoad agents
        for l in loads:
            self.loads[l] = NetworkLoad(local='127.0.0.1:500{}'.format(l))
            self.executor.submit(self.loads[l].run)
            self.allocation_id[l] = 0
            self.loads[l].curr_allocation = {
                'allocation_id':0, 
                'allocation_value':self.net.load['p_kw'][l],
                'allocation_duration':0
                }
    
    def connect_network(self):
        for l in self.loads:
            self.loads[l].schedule(action=self.loads[l].send_join,
                    args={'dst':self.allocator.local}, time=l)

    def stop(self):
        self.allocator.stop_network()
        self.allocator = None
        self.executor.shutdown()

    def broadcast(self):
        if self.allocator is None:
            raise RuntimeError("no allocator")

        print("Broadcasting OPF results")
        for l in self.loads:
            if self.net.load['controllable'][l] is True:
                allocation_value = self.net.res_load['p_kw'][l].item()
                allocation = {
                    'allocation_id':self.allocation_id[l], 
                    'duration':0,
                    'allocation_value':allocation_value
                    }
                self.allocation_id[l] += 1
                self.allocator.schedule(
                    action=self.allocator.send_allocation, 
                    args={'agent_id':self.loads[l].agent_id, 'allocation':allocation}
                    )

    def collect(self): 
        if self.allocator is None:
            raise RuntimeError("no allocator")
        print("Collecting network allocations")

        for l in self.loads:
            v = self.allocator.loads[self.loads[l].agent_id]['allocation_value']
            net.load['p_kw'][l] = v

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
    pp.create_load(net, bus[1], p_kw=70e3, min_p_kw=40e3, 
    max_p_kw=70e3, min_q_kvar=0, max_q_kvar=0, controllable=True),
    pp.create_load(net, bus[1], p_kw=70e3, controllable=False),
    pp.create_load(net, bus[2], p_kw=10e3, controllable=False)
]

elec = ElectricalSimulator(net=net)
elec.create_allocator()
elec.add_loads(loads)
elec.connect_network()

def random_alloc(load):
    while elec.allocator is not None:
        v = load.curr_allocation['allocation_value'] #random() * 1.0e5
        allocation = {'alloaction_id':0, 'allocation_value':v, 'duration':0}
        load.curr_allocation = allocation
        load.schedule(action=load.allocation_report, time=0.5)
        sleep(1)

def opf_loop():
    while elec.allocator is not None:
        sleep(5)
        elec.optimize_pf()
        print(elec.net.res_load)
        print(elec.net.res_gen)
        elec.broadcast()        
        sleep(5)
        elec.collect()
        print(elec.net.load)

def load_csv(load, file):
    # Data prepation
    loads = []
    with open(file, newline='') as csvfile:
        reader = csv.reader(csvfile, delimiter=',')
        for row in reader:
            if row[0] != 'timedelta' and float(row[1]) != 0 :
                loads.append([float(row[0]), float(row[1]), float(row[2])])
        
        for i in range(0, len(loads)):
            loads[i][0] = i+1
    # Scheduling allocation
    while elec.allocator is not None and len(loads) > 0:
        v = loads.pop(0)
        allocation = {'alloaction_id':0, 'allocation_value':v[1], 'duration':0}
        load.schedule(action=load.allocation_handle, args={'allocation':allocation}, time=v[0])
        load.schedule(action=load.allocation_report, time=v[0])

elec.executor.submit(opf_loop)
elec.executor.submit(random_alloc, elec.loads[1])
elec.executor.submit(load_csv(elec.loads[2], 'PV_Nelly_House_1.csv'))

