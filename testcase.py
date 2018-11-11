from sins import NetworkAllocator, NetworkLoad
from concurrent.futures import ThreadPoolExecutor
import signal
from time import sleep
from random import random
from itertools import dropwhile
import pandapower as pp
import numpy as np

class ElectricalSimulator:
    """ Simulate a communicating policy allocator
    """
    def __init__(self):
        self.net = pp.create_empty_network()
        self.loads = {}
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.bus = {}
        self.allocation_id = {}

    def bootstrap(self):
        # create buses
        self.bus[1] = pp.create_bus(self.net, vn_kv=220.)
        self.bus[2] = pp.create_bus(self.net, vn_kv=110.)
        self.bus[3] = pp.create_bus(self.net, vn_kv=110.)
        self.bus[4] = pp.create_bus(self.net, vn_kv=110.)

        # create 220/110 kV transformer
        pp.create_transformer(
            self.net, self.bus[1], self.bus[2], 
            std_type="100 MVA 220/110 kV"
            )

        # create 110 kV lines
        pp.create_line(
            self.net, self.bus[2], self.bus[3], 
            length_km=70., std_type='149-AL1/24-ST1A 110.0'
            )
        pp.create_line(
            self.net, self.bus[3], self.bus[4], 
            length_km=50., std_type='149-AL1/24-ST1A 110.0'
            )
        pp.create_line(
            self.net, self.bus[4], self.bus[2], 
            length_km=40., std_type='149-AL1/24-ST1A 110.0'
            )

    def optimize_pf(self):
        pp.runopp(self.net, verbose=True)
        return self.net
    
    def create_allocator(self):
        self.allocator = NetworkAllocator(local='127.0.0.1:5555')
        handler = lambda signum, frame: self.stop()
        signal.signal(signal.SIGINT, handler)
        self.executor.submit(self.allocator.run)

    def create_loads(self):
        # create generators
        eg = pp.create_ext_grid(
            self.net, self.bus[1], min_p_kw=-1e9, 
            max_p_kw=1e9
            )
        g0 = pp.create_gen(
            self.net, self.bus[3], p_kw=-80 * 1e3, 
            min_p_kw=-80e3, max_p_kw=0, vm_pu=1.01, 
            controllable=True
            )
        g1 = pp.create_gen(
            self.net, self.bus[4], p_kw=-100 * 1e3, 
            min_p_kw=-100e3, max_p_kw=0, vm_pu=1.01, 
            controllable=True
            )
        costeg = pp.create_polynomial_cost(
            self.net, 0, 'ext_grid', np.array([-1, 0])
            )
        costgen1 = pp.create_polynomial_cost(
            self.net, 0, 'gen', np.array([-1, 0])
            )
        costgen2 = pp.create_polynomial_cost(
            self.net, 1, 'gen', np.array([-1, 0])
            )

        # create loads
        loads = [
            pp.create_load(self.net, self.bus[2], p_kw=70e3, min_p_kw=40e3, 
            max_p_kw=70e3, min_q_kvar=0, max_q_kvar=0, controllable=True),
            pp.create_load(self.net, self.bus[3], p_kw=70e3, controllable=False),
            pp.create_load(self.net, self.bus[4], p_kw=10e3, controllable=False)
            ]
        # Create associated NetworkLoad agents
        for l in loads:
            self.loads[l] = NetworkLoad(local='127.0.0.1:500{}'.format(l))
            self.executor.submit(self.loads[l].run)
            self.allocation_id[l] = 0
        self.loads[0].curr_allocation = {'allocation_id':0, 'allocation_value':70e3, 'allocation_duration':0}
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
            return

        print("Broadcasting OPF results")
        for l in self.loads:
            allocation_value = self.net.res_load['p_kw'][l]
            allocation_value= allocation_value.item()
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
            
            # Only update l == 0
            break

    def collect(self):
        print("Collecting network allocations")
        if self.allocator is None:
            return
        for l in self.loads:
            v = self.allocator.loads[self.loads[l].agent_id]['allocation_value']
            self.net.load['p_kw'][l] = v

elec = ElectricalSimulator()
elec.bootstrap()
elec.create_allocator()
elec.create_loads()
elec.connect_network()

#elec.optimize_pf()
def opf_loop():
    while elec.allocator is not None:
        sleep(5)
        net = elec.optimize_pf()
        print(net.res_load)
        elec.broadcast()
        sleep(5)
        elec.collect()
        print(net.load)

def random_alloc(load):
    while elec.allocator is not None:
        v = random() * 1.0e5
        allocation = {'alloaction_id':0, 'allocation_value':v, 'duration':0}
        load.curr_allocation = allocation
        load.schedule(action=load.report_allocation, time=0.5)
        sleep(1)

elec.executor.submit(opf_loop)
elec.executor.submit(random_alloc, elec.loads[1])
elec.executor.submit(random_alloc, elec.loads[2])