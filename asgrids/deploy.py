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
from .defs import Allocation, Packet
from .controller import PIController
import logging
import sys, traceback

class SmartGridSimulation(object):
    def __init__(self):
        self.nodes: dict = {}
        self.conns: dict = {}
        self.remote_machines: list = []
        self.remote_servers: list = []
        self.server_threads: list = []
        self.network_ready: Queue = Queue(1)
        self.network_count: list = []
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
    Make sure 'asgrids' library is available remotely
    """
    def check_remote(self, remote_machine, username):
        import os
        import asgrids
        remote_server = DeployedServer(remote_machine)
        conn = remote_server.classic_connect()
        site = conn.modules.site
        python_pkg_path = site.getsitepackages()[0].split('/')[-2:]
        python_pkg_path = "/home/{}/.local/lib/{}/{}".format(username, python_pkg_path[0], python_pkg_path[1])
        conn.execute("import sys")
        conn.execute("sys.path.append('{}')".format(python_pkg_path))
        try:
            conn.execute('import asgrids')
        except Exception as e:
            print(e)
            # Making sure all asgrids requirements are installed remotely
            curr_path = os.path.dirname(os.path.realpath(__file__))
            pkgs = ""
            # remote_machine["pip"]["install"]["--user"]["-U"]["pip"]()
            with open(f"{curr_path[:-8]}/requirements.txt", 'r') as fp:
                for cnt, pkgname in enumerate(fp):
                    pkgs = f" {pkgname}"
                    # remote_machine["pip"]["install"]["--user"]["{}".format(pkgname)]()
            remote_machine.popen(f"pip install --user {pkgs}")
            rpyc.classic.upload_package(
                conn, asgrids, os.path.join(python_pkg_path, "asgrids"))
            remote_server.close()
            conn.close()
            remote_server = DeployedServer(remote_machine)
            conn = remote_server.classic_connect()
            conn.execute("import sys")
            conn.execute("sys.path.append('{}')".format(python_pkg_path))
        
        return remote_server, conn

    """
    Create node with type 'ntype' on the remote machine `hostname`
    Returns a rpyc object wrapper, that enables handling the remote object
    as if it was created locally.
    """

    def create_remote_node(self, hostname, username, keyfile, ntype, addr):
        remote_machine = SshMachine(
            host=hostname, user=username, keyfile=keyfile)
        PATH = remote_machine.env["PATH"]
        remote_machine.env["PATH"]=f"/home/{username}/.local/bin:{PATH}"
        remote_server, conn = self.check_remote(remote_machine, username)
        self.remote_machines.append(remote_machine)
        self.remote_servers.append(remote_server)
        serving_thread = BgServingThread(conn)
        self.server_threads.append(serving_thread)
        self.conns[addr] = conn
        try:
            conn.modules.sys.stdout = sys.stdout
            # conn.modules.sys.stderr = sys.stderr
        except Exception as e:
            print(f"Error seting remote stdout/stderr: {e}")

        # Using execute/eval allows working on a remote single namespace
        # useful when teleporting functions that need using remote object names
        # as using conn.modules create a locate but not a remote namespace member
        if ntype is 'load':
            conn.execute("from asgrids import NetworkLoad")
            conn.execute("from sys import stdout")
            conn.execute(f"node=NetworkLoad(stdout=stdout)")
            conn.execute("node.local='{}'".format(addr))
            node = conn.namespace['node']

        elif ntype is 'allocator':
            conn.execute("from asgrids import NetworkAllocator")
            conn.execute("node=NetworkAllocator()")
            node = conn.namespace['node']
        else:
            raise ValueError("Can't handle ntype == {}".format(ntype))
        
        node.joined_callback = self.joined_network
        self.nodes[addr] = node

        # Return node netref object and rpyc connection
        return node, conn

    """
    Creates a local node
    """
    def create_node(self, ntype, addr, mode='udp'):
        if ntype is 'load':
            node = NetworkLoad(mode=mode)
        elif ntype is 'allocator':
            node = NetworkAllocator(mode=mode)
        node.local = addr
        node.joined_callback = self.joined_network
        self.nodes[addr] = node
        return node

    def get_node(self, ind):
        return self.nodes[ind]

    """
    Start the network nodes
    """
    def start(self, skip_join=False):
        allocator = list(filter(lambda node: node.type == "NetworkAllocator", [*self.nodes.values()]))[0]
        for _, node in self.nodes.items():
            try:
                node.run()
            except Exception as e:
                print(e)
            if node.type=="NetworkLoad":
                packet = Packet('join_ack', src=allocator.local, dst=node.local)
                node.handle_receive(packet)

        if not skip_join:
            print("waiting for {} nodes to join network".format(len(self.nodes)))
            self.network_ready.get()
        return time()

    def joined_network(self, src, dst):
        self.network_count.append(src)
        if len(self.network_count) == len(self.nodes) and len(self.nodes) != 0:
            self.network_ready.put(1)

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


    def runpp(self, net, allocations_queue: Queue, measure_queues: dict, initial_time=0, logger=None):
        """Perform power flow analysis to collect voltage values of all the buses
        
        Args:
            net ([type]): pandapower network
            allocations_queue (Queue): Contains updated p,q values that will be fed to the power flow analysis loop
            measure_queues (dict): Measure results will be stored here
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
                # else:
                #     return
        except LoadflowNotConverged as e:
            print("runpp failed miserably: {}".format(e))
            return
        except Empty:
            return
        except Exception as e:
            print(e)
            return

        # Updating voltage measures for clients
        if changed:
            for node in measure_queues:
                bus_ind = 0
                try:
                    bus_ind = net.load['bus'][net.load['name'] == node].item()
                except Exception as e:
                    raise(e)
                # print("bus_ind: {}".format(bus_ind))
                # print("net.res_bus: {}".format(net.res_bus))
                vm_pu = net.res_bus['vm_pu'][bus_ind].item()
                try:
                    measure_queues[node].get_nowait()
                except Empty:
                    measure_queues[node].put(vm_pu)

    def optimize_network_opf(self, net, allocator, voltage_values, duty_cycle=10, max_vm=1.05, forecast=True, check_limit=True):
        qsize = voltage_values.qsize()  # Getting all measurements from the queue at once
        optimize = False
        print("checking voltage violations")
        for _ in range(qsize):
            try:
                nid, allocation = voltage_values.get()
                net.load.loc[net.load['name'] == nid, 'p_kw'] = allocation[0].p_value
                if forecast:
                    if allocation[0].p_value <=0:
                        net.load.loc[net.load['name'] == nid, 'min_p_kw'] = allocation[1].p_value
                # print(net.load[net.load['name'] == nid]['min_p_kw'].item())
            except Exception as e:
                print("Error getting voltage value from queue: {}".format(e))
            if nid == 0:
                print("Terminating optimize_network_opf")
                return
            v = allocation[2]
            if v >= max_vm:# or v <= 0.96:
                optimize = True
        
        if not optimize and check_limit:
            return
        try:
            c_loads = net.load[net.load['controllable'] == True]
        except Exception as e:
            print("Error getting list of controllable loads: {}".format(e))        
        try:
            pp.runopp(net, init='pf', verbose=False)
        except OPFNotConverged as e:
            print("Runopp failed: {}".format(e))
            for row in c_loads.iterrows():
                p = 0
                q = 0
                name = row[1]['name']
                allocation = Allocation(0, p, q, duty_cycle*3)
                # print("OPF SENT ALLOCATION {} to {}".format(0 , name))
                allocator.send_allocation(nid=name, allocation=allocation)
            return
        except Exception as e:
            print("What the fuck: {}: {}".format(type(e).__name__, e.args))

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
                allocation = Allocation(0, p, q, duty_cycle*3)
                # allocator.schedule(action=allocator.send_allocation, args=[name, allocation])
                allocator.send_allocation(nid=name, allocation=allocation)
                # print("OPF SENT ALLOCATION {}:{} to {}".format(p, q , name))
            except Exception as e:
                print("Error scheduing allocation: {}".format(e))
                print("Terminating OPF controller")
                raise(e)

    def optimize_network_pi(self, net, allocator, voltage_values: Queue, duty_cycle=10, max_vm=1.05, check_limit=True, accel=1.0):
        if not hasattr(self, 'controller'):
            print("Creating PIController: max_vm = %f"%max_vm)
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
                nid, allocation = voltage_values.get()
                if nid == 0:
                    print("Terminating optimize_network_pi")
                    return
                v = allocation[2]
                if v >=max_vm - 0.01:
                    optimize = True
                values[nid] = v
        except Exception as e:
            print(e)

        if not optimize and check_limit:
            return
        print("Optimizing")
        for name in net.load['name']:
            bus_id = net.load.loc[net.load['name']==name, 'bus'].item()
            try:
                if not hasattr(net, 'res_bus'):
                    return
                v = net.res_bus.loc[bus_id]['vm_pu']*net.bus.loc[bus_id]['vn_kv']*1000 # converting nominal value to V
            except Exception as e:
                print(e)
                return
            if net.load.loc[net.load['name']==name, 'controllable'].item() == True:
                nids.append(name)
                gen_vs.append(v)
            else:
                try:
                    load_vs.append(v)
                    # Using loads (non-generators) allocations from net as their maximum allocations (shouldn't have big effect)
                    # Maximum allocation for generators are -30kW
                    load_max_as.append(
                        net.load.loc[net.load['name'] == nid, 'p_kw'].item()*1e3)
                except Exception as e:
                    print(e)
                    return
        try:
            _, pv_a = self.controller.generate_allocations(
                load_vs, gen_vs, load_max_as, [-30e3]*len(gen_vs))
        except Exception as e:
            print("Error generating allocations: {}".format(e))
            raise e
        # print("optimizing {}".format(nid))
        try:
            for a, nid in zip(pv_a, nids):
                allocation = Allocation(
                    a.aid, a.p_value/1e3, a.q_value/1e3, duty_cycle)
                allocator.send_allocation(nid, allocation)
        except Exception as e:
            print(e)
            print("Terminating PI controller")
