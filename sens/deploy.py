# -*- coding: utf-8 -*-


"""
This defines a smart grid simulation environment
It handles deployment/execution of local and remote nodes
"""

import rpyc
from plumbum import SshMachine
from rpyc.utils.classic import deliver, teleport_function
from rpyc.utils.helpers import BgServingThread
from rpyc.utils.zerodeploy import DeployedServer
from queue import Queue, Full, Empty
from time import monotonic as time, sleep
from pandapower import pp, OPFNotConverged, LoadflowNotConverged
from .network_allocator import NetworkAllocator
from .network_load import NetworkLoad
from .defs import Allocation
from .controller import PIController
import logging
import sys, traceback
# logging.basicConfig(filename='simulation.log',
#                             filemode='a',
#                             format='%(message)s',
#                             # datefmt='%H:%M:%S',
#                             level=logging.DEBUG)
# logger = logging.getLogger('SmartGridSimulation')
# logger.setLevel(logging.INFO)
# fh = logging.FileHandler('simulation.log', mode='w')
# fh.setLevel(logging.INFO)
# logger.addHandler(fh)


class SmartGridSimulation(object):
    def __init__(self):
        self.nodes = {}
        self.conns = {}
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []

        # provide rpyc's deliver as a local function
        # This function allows deliver objects to remote machines
        self.deliver = deliver

        # provide rpyc's deliver as a local function
        # This function allows delivering objects to remote machines
        # NOTE Expect remote node object name to be always "node"
        # callable arguments should be rpyc's netrefs to use remote objects,
        # and avoid re-uploading.
        self.teleport = teleport_function
        self.shutdown = False

    """
    Make sure 'sens' library is available remotely
    """

    @staticmethod
    def check_remote(remote_server, python_pkg_path="/home/ubuntu/.local/lib/python3.6/site-packages/"):
        conn = remote_server.classic_connect()
        import os
        import sens

        rpyc.classic.upload_package(
            conn, sens, os.path.join(python_pkg_path, "sens"))
        return False

    """
    Create node with type 'ntype' on the remote machine `hostname`
    Returns a rpyc object wrapper, that enables handling the remote object
    as if it was created locally.
    """

    def create_remote_node(self, hostname, username, keyfile, ntype, addr, config=None):
        if config is None:
            config = {}
        remote_machine = SshMachine(
            host=hostname, user=username, keyfile=keyfile)
        remote_server = DeployedServer(remote_machine)
        # if `sens` wasn't available remotely, now we installed it
        # but we need to reconnect to get an updated conn.modules
        # TODO Might not be needed if using execute/eval
        if not self.check_remote(remote_server):
            remote_server.close()
            remote_server = DeployedServer(remote_machine)

        self.remote_machines.append(remote_machine)
        self.remote_servers.append(remote_server)
        conn = remote_server.classic_connect()
        serving_thread = BgServingThread(conn)
        self.server_threads.append(serving_thread)
        self.conns[addr] = conn

        # Using execute/eval allows working on a remote single namespace
        # useful when teleporting functions that need using remote object names
        # as using conn.modules create a locate but not a remote namespace member
        if ntype is 'load':
            conn.execute("from sens import NetworkLoad")
            conn.execute("node=NetworkLoad()")
            conn.execute("node.local={}".format(addr))
            node = conn.namespace['node']
        elif ntype is 'allocator':
            conn.execute("from sens import NetworkAllocator")
            conn.execute("node=NetworkAllocator()")
            node = conn.namespace['node']
        else:
            raise ValueError("Can't handle ntype == {}".format(ntype))
        self.nodes[addr] = node

        # Return node netref object and rpyc connection
        return node, conn

    """
    Creates a local node
    """

    def create_node(self, ntype, addr, identity=None):
        if ntype is 'load':
            node = NetworkLoad()
            node.local = addr
            if identity:
                node.identity = identity
            self.nodes[addr] = node
            return node
        elif ntype is 'allocator':
            node = NetworkAllocator()
            node.local = addr
            self.nodes[addr] = node
            return node

    """
    Runs the created remote objects
    """

    def run(self):
        for node in self.nodes:
            node.run()

    def get_node(self, ind):
        return self.nodes[ind]

    """
    Stops the remotely created nodes
    """

    def stop(self):
        for _, node in self.nodes.items():
            node.stop()
        for server in self.remote_servers:
            server.close()
        self.nodes = {}
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []
        self.shutdown = True


    def runpp(self, net, allocations_queue: Queue, measure_queues: dict, plot_queue: Queue, with_plot=False, initial_time=0, logger=None):
        """Perform power flow analysis to collect voltage values of all the buses
        
        Args:
            net ([type]): pandapower network
            allocations_queue (Queue): Contains updated p,q values that will be fed to the power flow analysis loop
            measure_queues (dict): Measure results will be stored here
            plot_queue (Queue): values sotred here are destined for plotting
            with_plot (bool, optional): Defaults to False. Whether or not to generate plot values
            initial_time (int, optional): Defaults to 0.
        """
        qsize = allocations_queue.qsize()
        changed = False
        if qsize == 0:
            return
            # print("runpp: updating {} new allocations".format(qsize))
        try:
            for i in range(qsize):
                timestamp, name, p_kw, q_kw = allocations_queue.get_nowait()
                if timestamp == name == p_kw == q_kw == 0:
                    print("Terminating runpp")
                    return
                if net.load.loc[net.load['name'] == name, 'p_kw'].item() != p_kw:
                    net.load.loc[net.load['name'] == name, 'p_kw'] = p_kw
                    changed = True
                if net.load.loc[net.load['name'] == name, 'q_kvar'].item() != q_kw:
                    net.load.loc[net.load['name'] == name, 'q_kvar'] = q_kw
                    changed = True

                if changed:
                    pp.runpp(net, init='results', verbose=True)
                    if logger is not None and changed:
                        T = time()
                        logger.info('LOAD {}\t{}\t{}'.format(
                                T, name, p_kw))
                        for i in net.bus.index:
                            logger.info('VOLTAGE {}\t{}\t{}'.format(
                                T, net.bus.loc[i, 'name'], net.res_bus.loc[i, 'vm_pu']))
                else:
                    return
        except LoadflowNotConverged as e:
            print("runpp failed miserably: {}".format(e))
            return
        except Empty:
            return
        except Exception as e:
            # exc_type, exc_value, exc_traceback = sys.exc_info()
            # print("What the fuck at runpp:")
            # print("*** format_tb:")
            # print(repr(traceback.format_tb(exc_traceback)))
            print(e)
            return

        # Updating voltage measures for clients and live_plot
        for node in measure_queues:
            bus_ind = 0
            try:
                bus_ind = net.load['bus'][net.load['name'] == node].item()
            except Exception as e:
                raise(e)
            vm_pu = net.res_bus['vm_pu'][bus_ind].item()
            try:
                measure_queues[node].get_nowait()
            except Empty:
                measure_queues[node].put(vm_pu)

    def optimize_network_opf(self, net, allocator, voltage_values, duty_cycle=10, max_vm=1.01):
        qsize = voltage_values.qsize()  # Getting all measurements from the queue at once
        optimize = False
        for _ in range(qsize):
            try:
                nid, v = voltage_values.get()
            except Exception as e:
                print("Error getting voltage value from queue: {}".format(e))
            if nid == v == 0:
                print("Terminating optimize_network_opf")
                return
            if v >= max_vm:# or v <= 0.96:
                optimize = True
        
        if not optimize:
            return
        
        try:
            pp.runopp(net, verbose=False)
        except OPFNotConverged as e:
            print("Runopp failed: {}".format(e))
            return
        except Exception as e:
            print("What the fuck: {}: {}".format(type(e).__name__, e.args))
        try:
            c_loads = net.load[net.load['controllable'] == True]
        except Exception as e:
            print("Error getting list of controllable loads: {}".format(e))

        print("optimizing {} nodes".format(len(c_loads.index)))
        for row in c_loads.iterrows():
            try:
                p = net.res_load['p_kw'][row[0]].item()
                q = net.res_load['q_kvar'][row[0]].item()
                name = row[1]['name']
            except Exception as e:
                print("Error in opf, couldn't read p,q from net.res_load: {}".format(e))
                raise(e)
            try:
                allocation = Allocation(0, p, q, duty_cycle)
                allocator.send_allocation(nid=name, allocation=allocation)
            except Exception as e:
                print("Error scheduing allocation: {}".format(e))
                print("Terminating OPF controller")
                raise(e)

    def optimize_network_pi(self, net, allocator, voltage_values: Queue, duty_cycle=10, max_vm=1.01):
        if not hasattr(self, 'controller'):
            print("Creating PIController")
            self.controller = PIController(maximum_voltage=400*max_vm, duration=duty_cycle)
        nids = []
        gen_vs: list = []  # List of generators(PV) current voltages
        load_vs: list = []  # List of non-generators current voltages
        load_max_as: list = []  # List of maximum allocations allowed for non-generators
        # while len(net.load['name'].tolist()) < len(gen_vs) + len(load_vs):
        qsize = voltage_values.qsize()  # Getting all measurements from the queue at once
        values: dict = {}
        # Some measures could be updates for the same nodes
        # We only take the most recent measures
        # We also clean up the queue along the way
        optimize = False
        try:
            for _ in range(qsize):
                nid, v = voltage_values.get()
                if nid == v == 0:
                    print("Terminating optimize_network_pi")
                    return
                values[nid] = v
                if v >= max_vm:
                    optimize = True
        except Exception as e:
            print(e)
        if not optimize:
            return
        if len(values) > 0:
            print("Optimizing {} nodes".format(len(values)))
        for nid, v in values.items():
            if v >= 1.04:
                print("Node {} above max threshold".format(nid))
            elif v  <= 0.96:
                print("node {} under min threshold".format(nid))
            # We wanna know the actual voltage of the bus
            # if nid in net.load['name'].tolist():
            #     bus_id = net.load.loc[net.load['name'] == nid, 'bus'].item()
            # elif nid in net.sgen['name'].tolist():
            #     bus_id = net.sgen.loc[net.sgen['name'] == nid, 'bus'].item()
            #bus_vn = net.bus['vn_kv'][bus_id].item()*1e3
            bus_vn = 400  # v
            try:
                # Listing all controllable loads, these are the PV generators that will be optimized
                pv_gens = net.load.loc[net.load['controllable']
                                    == True]['name'].tolist()
            except Exception as e:
                print(e)
            
            if nid in pv_gens:
                nids.append(nid)
                # converting nominal values to absolute values in V
                gen_vs.append(v*bus_vn)
            else:
                # converting nominal values to absolute values in V
                load_vs.append(v*bus_vn)
                try:
                    # Using loads (non-generators) allocations from net as their maximum allocations (shouldn't have big effect)
                    # Maximum allocation for generators are -30kW
                    load_max_as.append(
                        net.load.loc[net.load['name'] == nid, 'p_kw'].item()*1e3)
                except Exception as e:
                    print(e)
        try:
            if len(gen_vs) > 0:
                # print("Optimizing {}".format([nid for nid in nids]))
                _, pv_a = self.controller.generate_allocations(
                    load_vs, gen_vs, load_max_as, [-30e3]*len(gen_vs))
                # print(len(pv_a))
            else:
                return
        except Exception as e:
            print("Error generating allocations: {}".format(e))
            raise e
        # print("optimizing {}".format(nid))
        try:
            for a, nid in zip(pv_a, nids):
                allocation = Allocation(
                    a.aid, a.p_value/1e3, a.q_value/1e3, duty_cycle)
                allocator.send_allocation(nid=nid, allocation=allocation)
        except Exception as e:
            print(e)
            print("Terminating PI controller")
        values = {}


# def live_plot_voltage(buses, plot_values, interval=10):
#     from math import ceil, sqrt
#     from matplotlib import pyplot as plt, animation
#     import numpy as np

#     fig = plt.figure()
#     ax = {}
#     lines = {}
#     min_lines = {}
#     max_lines = {}
#     grid_dim = ceil(sqrt(len(buses)))
#     i = 1
#     for bus in buses:
#         ax[bus] = plt.subplot(grid_dim, grid_dim, i)
#         lines[bus] = ax[bus].plot([], [])[0]
#         min_lines[bus] = ax[bus].plot([], [], color='red')[0]
#         max_lines[bus] = ax[bus].plot([], [], color='red')[0]
#         i = i + 1
#     plt.subplots_adjust(hspace=0.7, bottom=0.2)

#     def init():
#         try:
#             for bus, a in ax.items():
#                 min_value = 0.96
#                 max_value = 1.04
#                 a.set_title('voltage value (p.u.) - bus {}'.format(bus))
#                 a.set_ylim([min_value*0.99, max_value*1.01])

#                 lines[bus].set_data([], [])
#                 min_lines[bus].set_data([0], [min_value])
#                 max_lines[bus].set_data([0], [max_value])
#         except Exception as e:
#             print("Error at live_plot init {}".format(e))

#         artists = [line for _, line in lines.items()]
#         artists = artists + [line for _, line in min_lines.items()]
#         artists = artists + [line for _, line in max_lines.items()]
#         artists = artists + [a for _, ax in ax.items()]

#         return artists

#     def data_gen():
#         while True:
#             timestamp = {}
#             value = {}
#             try:
#                 qsize = plot_values.qsize()
#                 if qsize == 0:
#                     yield None, None
#                 for _ in range(qsize):
#                     t, b, v = plot_values.get_nowait()
#                     if b not in buses:
#                         continue
#                     else:
#                         if b not in value:
#                             timestamp[b] = []
#                             value[b] = []
#                         timestamp[b].append(t)
#                         value[b].append(v)
#             except Exception as e:
#                 print(e)
#                 raise e
#             if timestamp == 0:
#                 break
#             yield timestamp, value

#     def animate(data):
#         t, v = data
#         artists = []
#         if t is None:
#             return artists
#         try:
#             for bus_id in v:
#                 xmin, xmax = ax[bus_id].get_xlim()
#                 ymin, ymax = ax[bus_id].get_ylim()
#                 if len(lines[bus_id].get_ydata()) == 0:
#                     ax[bus_id].set_xlim(max(t[bus_id]), 2 * max(t[bus_id]))
#                     ax[bus_id].relim()
#                 if max(t[bus_id]) >= xmax:
#                     ax[bus_id].set_xlim(xmin, max(t[bus_id]) + 1)
#                     ax[bus_id].relim()
#                 if max(v[bus_id]) >= ymax:
#                     ax[bus_id].set_ylim(ymin, max(v[bus_id]) + 0.005)
#                     ax[bus_id].relim()
#                 if min(v[bus_id]) <= ymin:
#                     ax[bus_id].set_ylim(min(v[bus_id]) - 0.005, ymax)
#                     ax[bus_id].relim()

#                 xdata = np.append(lines[bus_id].get_xdata(), t[bus_id])
#                 ydata = np.append(lines[bus_id].get_ydata(), v[bus_id])
#                 lines[bus_id].set_data(xdata, ydata)

#                 xdata = min_lines[bus_id].get_xdata()
#                 ydata = min_lines[bus_id].get_ydata()

#                 min_lines[bus_id].set_data(np.append(xdata, t[bus_id]), np.append(
#                     ydata, [ydata[0]]*len(t[bus_id])))

#                 xdata = max_lines[bus_id].get_xdata()
#                 ydata = max_lines[bus_id].get_ydata()
#                 max_lines[bus_id].set_data(np.append(xdata, t[bus_id]), np.append(
#                     ydata, [ydata[0]]*len(t[bus_id])))

#             artists = artists + [line for _, line in lines.items()]
#             artists = artists + [line for _, line in max_lines.items()]
#             artists = artists + [line for _, line in min_lines.items()]
#             artists = artists + [a for _, a in ax.items()]
#         except Exception as e:
#             print("Exception when filling lines {}".format(e))
#         return artists

#     anim = animation.FuncAnimation(fig, animate, data_gen, init_func=init,
#                                    interval=interval, blit=False, repeat=False)
#     try:
#         plt.autoscale(True)
#         plt.show()
#     except Exception as e:
#         print("Error at plt.show {}".format(e))


# def live_plot_load(loads, plot_values, interval=10):
#     from math import ceil, sqrt
#     from matplotlib import pyplot as plt, animation
#     import numpy as np

#     fig = plt.figure()
#     ax = {}
#     lines = {}
#     min_lines = {}
#     max_lines = {}
#     grid_dim = ceil(sqrt(len(loads)))
#     i = 1
#     for load in loads:
#         ax[load] = plt.subplot(grid_dim, grid_dim, i)
#         lines[load] = ax[load].plot([], [])[0]
#         min_lines[load] = ax[load].plot([], [], color='red')[0]
#         max_lines[load] = ax[load].plot([], [], color='red')[0]
#         i = i + 1
#     plt.subplots_adjust(hspace=0.7, bottom=0.2)

#     def init():
#         try:
#             for bus, a in ax.items():
#                 min_value = 0.96
#                 max_value = 1.04
#                 a.set_title('load value (kW) - load {}'.format(bus))
#                 a.set_ylim([min_value*0.99, max_value*1.01])

#                 lines[bus].set_data([], [])
#                 min_lines[bus].set_data([0], [min_value])
#                 max_lines[bus].set_data([0], [max_value])
#         except Exception as e:
#             print("Error at live_plot init {}".format(e))

#         artists = [line for _, line in lines.items()]
#         artists = artists + [line for _, line in min_lines.items()]
#         artists = artists + [line for _, line in max_lines.items()]
#         artists = artists + [a for _, ax in ax.items()]

#         return artists

#     def data_gen():
#         while True:
#             timestamp = {}
#             value = {}
#             try:
#                 qsize = plot_values.qsize()
#                 if qsize == 0:
#                     yield None, None
#                 for _ in range(qsize):
#                     t, b, v = plot_values.get_nowait()
#                     if b not in buses:
#                         continue
#                     else:
#                         if b not in value:
#                             timestamp[b] = []
#                             value[b] = []
#                         timestamp[b].append(t)
#                         value[b].append(v)
#             except Exception as e:
#                 print(e)
#                 raise e
#             if timestamp == 0:
#                 break
#             yield timestamp, value

#     def animate(data):
#         t, v = data
#         artists = []
#         if t is None:
#             return artists
#         try:
#             for lid in v:
#                 xmin, xmax = ax[lid].get_xlim()
#                 ymin, ymax = ax[lid].get_ylim()
#                 if len(lines[lid].get_ydata()) == 0:
#                     ax[lid].set_xlim(max(t[lid]), 2 * max(t[lid]))
#                     ax[lid].relim()
#                 if max(t[bus_id]) >= xmax:
#                     ax[lid].set_xlim(xmin, max(t[lid]) + 1)
#                     ax[lid].relim()
#                 if max(v[lid]) >= ymax:
#                     ax[lid].set_ylim(ymin, max(v[lid]) + 0.005)
#                     ax[lid].relim()
#                 if min(v[lid]) <= ymin:
#                     ax[lid].set_ylim(min(v[lid]) - 0.005, ymax)
#                     ax[lid].relim()

#                 xdata = np.append(lines[lid].get_xdata(), t[lid])
#                 ydata = np.append(lines[lid].get_ydata(), v[lid])
#                 lines[lid].set_data(xdata, ydata)

#                 xdata = min_lines[lid].get_xdata()
#                 ydata = min_lines[lid].get_ydata()

#                 min_lines[lid].set_data(np.append(xdata, t[lid]), np.append(
#                     ydata, [ydata[0]]*len(t[lid])))

#                 xdata = max_lines[lid].get_xdata()
#                 ydata = max_lines[lid].get_ydata()
#                 max_lines[lid].set_data(np.append(xdata, t[lid]), np.append(
#                     ydata, [ydata[0]]*len(t[lid])))

#             artists = artists + [line for _, line in lines.items()]
#             artists = artists + [line for _, line in max_lines.items()]
#             artists = artists + [line for _, line in min_lines.items()]
#             artists = artists + [a for _, a in ax.items()]
#         except Exception as e:
#             print("Exception when filling lines {}".format(e))
#         return artists

#     anim = animation.FuncAnimation(fig, animate, data_gen, init_func=init,
#                                    interval=interval, blit=False, repeat=False)
#     try:
#         plt.autoscale(True)
#         plt.show()
#     except Exception as e:
#         print("Error at plt.show {}".format(e))
