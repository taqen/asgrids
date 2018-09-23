import simpy.rt
import numpy as np
import pandapower as pp
from random import randint                
from async_communication import AsyncCommunication

RANDOM_SEED = 42
SIM_TIME = 100

class NetConsumer:
    """ A simulation of a communicating electrical network consumer.
    """
    def __init__(self):
        self.env = simpy.Environment()
        self.comm = AsyncCommunication()
        self.comm.start()
        self.remote_host = '127.0.0.1'
        self.remote_port = '5555'

    def scheduler(self, load=None, duration=None):
        """
        Schedule a consumption event for the specified load/duration, or generate random load/duration
        :param load:
        :param duration:
        """
        p_kw=load
        if p_kw is None:
            p_kw = randint(0, 600) * 1e2
        if duration is None:
            duration = randint(5, 10) * .1

        proc = self.env.process(self.consume(p_kw, duration))
        self.env.run(until=proc)

    def report_load(self, load, duration):
        """
        Report executed load to the main allocator to update OPF
        :param load:
        :param duration:
        """
        print("Reporting consumption of {} watt for {} minutes".format(load, duration))
        self.comm.send(request='{} {}'.format(load, duration), tcp_host=self.remote_host, tcp_port=self.remote_port)

    def create_load(self, p_kw=0, duration=0):
        print("Consuming {} watt for {} minutes".format(p_kw, duration))
        yield self.env.timeout(duration)
        self.report_load(p_kw, duration)

        

class NetAllocator:
    """ Simulate a communicating policy allocator
    """
    def __init__(self):
        self.env = simpy.Environment()
        self.comm = AsyncCommunication()

    def bootstrap(self):
        self.net = pp.create_empty_network()

        #create buses
        bus1 = pp.create_bus(self.net, vn_kv=220.)
        bus2 = pp.create_bus(self.net, vn_kv=110.)
        bus3 = pp.create_bus(self.net, vn_kv=110.)
        bus4 = pp.create_bus(self.net, vn_kv=110.)

        #create 220/110 kV transformer
        pp.create_transformer(self.net, bus1, bus2, std_type="100 MVA 220/110 kV")

        #create 110 kV lines
        pp.create_line(self.net, bus2, bus3, length_km=70., std_type='149-AL1/24-ST1A 110.0')
        pp.create_line(self.net, bus3, bus4, length_km=50., std_type='149-AL1/24-ST1A 110.0')
        pp.create_line(self.net, bus4, bus2, length_km=40., std_type='149-AL1/24-ST1A 110.0')

        #create loads
        pp.create_load(self.net, bus2, p_kw=60e3, controllable = False)
        pp.create_load(self.net, bus3, p_kw=70e3, controllable = False)
        pp.create_load(self.net, bus4, p_kw=100e3, controllable = False)

        #create generators
        eg = pp.create_ext_grid(self.net, bus1)
        g0 = pp.create_gen(self.net, bus3, p_kw=-80*1e3, min_p_kw=-80e3, max_p_kw=0,vm_pu=1.01, controllable=True)
        g1 = pp.create_gen(self.net, bus4, p_kw=-100*1e3, min_p_kw=-100e3, max_p_kw=0, vm_pu=1.01, controllable=True)
        costeg = pp.create_polynomial_cost(self.net, 0, 'ext_grid', np.array([1, 0]))
        costgen1 = pp.create_polynomial_cost(self.net, 0, 'gen', np.array([1, 0]))
        costgen2 = pp.create_polynomial_cost(self.net, 1, 'gen', np.array([1, 0]))

    def optimize_pf(self):
        pp.runopp(self.net, verbose=True)
        return self.net.res_gen
    
    def schedule(self):
        while True:
            self.optimize_pf()
            yield self.env.timeout(0)


def main():
    consumer = NetConsumer()
    producer = NetProducer()
    allocator = NetAllocator()

if __name__ == "__main__":
    main()
