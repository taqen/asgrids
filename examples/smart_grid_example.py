#!/usr/bin/env python
# -*- coding: utf-8 -*-

import random
import signal
from queue import Queue
from time import time
from typing import List

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import pandapower as pp

from asgrids import Allocation, SmartGridSimulation

# Define address of physical network nodes
# In this case, the first address is the allocator's
net_addr = ['10.10.10.1', '10.10.10.144', '10.10.10.45', '10.10.10.88', '10.10.10.253', '10.10.10.219']


# Used locally to load and prepare data
def load_csv(file, columns=None):
    if columns is None:
        columns = list()
    import pandas as pd

    # Data preparation
    curves = pd.read_csv(file)
    filtered = curves.filter(items=columns).values.tolist()
    return filtered


# to be used remotely to implement node's consumption behavior
# This is an example of how to schedule events from a loaded timeseries
def remote_func(node, loads):
    # For better performance it is better that
    # loads reference an already delivered netref object.
    # Scheduling allocations
    for v in loads:
        allocation = Allocation(0, v[1], v[2])
        node.schedule(action=node.allocation_handle,
                      args={'allocation': allocation},
                      delay=v[0],
                      callbacks=[node.allocation_report])


allocations_queue = Queue()  # type:Queue


def allocation_updated(allocation, node_addr):
    # We receive node_addr as "X.X.X.X:YYYY"
    # ind also identifies the node in pandapawer loads list
    print("allocation received allocation update")
    ind = net_addr.index(node_addr.split(":")[0])
    allocations_queue.put([time(), "Load_{}".format(ind), allocation.p_value, allocation.q_value])


def create_nodes(sim):
    # Create remote agents of type NetworkLoad
    for i in range(len(net_addr) - 1):
        # a bigger latency overhead is noted using netref objects (node)
        # Fortunately we can directly execute python remotely with conn
        node, conn = sim.create_remote_node(
            hostname=net_addr[i + 1], username='ubuntu', keyfile='~/.ssh/id_rsa.pub',
            ntype='load', addr='{}:{}'.format(remote_value, random.randint(6000, 9000)))
        # This will be address in the simulation network
        # "node" is already registered in remote namespace
        remote_value = sim.deliver(conn, net_addr[i + 1])
        # conn.execute("node.run()")
        node.run()
        remote_value = sim.deliver(conn, {'dst': '{}:5555'.format(net_addr[0])})
        # conn.execute("node.schedule(node.send_join, {{'dst':'{}:5555'}})".format(remote_value))
        node.schedule(node.send_join, remote_value)

        loads = load_csv('../victor_scripts/curves.csv', ['timestamp', 'load_%d_p' % (i + 1), 'load_%d_q' % (i + 1)])
        remote_loads = sim.deliver(conn, loads)
        remote_func(node, remote_loads)

    # for i in range(len(net_addr)-1):
    #     conn = sim.conns[i]
    #     loads = load_csv('../victor_scripts/curves.csv', ['timestamp','load_%d_p'%(i+1), 'load_%d_q'%(i+1)])
    #     remote_loads = sim.deliver(conn, loads)
    #     remote_func(node, remote_loads)
    # func(conn, loads)


def create_pp_net(net):
    b1 = pp.create_bus(net, vn_kv=0.4, name="MV/LV substation")  # LV side of the MV/LV transformer
    b2 = pp.create_bus(net, vn_kv=0.4, name="Load")  # connexion point for the 5 clients
    pp.create_ext_grid(net, bus=b1, vm_pu=1.025, name="MV network")  # 400 V source
    for i in range(5):
        pp.create_load(net, bus=b2, p_kw=0, q_kvar=0, name="Load_{}".format(i + 1))  # consumption meter
        pp.create_load(net, bus=b2, p_kw=0, q_kvar=0, name="PV_{}".format(i + 1))  # production meter
    pp.create_line_from_parameters(net,
                                   name="Line",  # name of the line
                                   from_bus=b1,  # Index of bus where the line starts"
                                   to_bus=b2,  # Index of bus where the line ends
                                   length_km=0.1,  # length of the line [km]
                                   r_ohm_per_km=0.411,  # resistance of the line [Ohm per km]
                                   x_ohm_per_km=0.12,  # inductance of the line [Ohm per km]
                                   c_nf_per_km=220,  # capacitance of the line [nano Farad per km]
                                   g_us_per_km=0,  # dielectric conductance of the line [micro Siemens per km]
                                   max_i_ka=0.282,  # maximal thermal current [kilo Ampere]
                                   )  # LV line (3x95 aluminium, Nexans ref. 10163510)
    return net


#########################################
# Create SmartGridSimulation environment
sim = SmartGridSimulation()
# Handle ctrl-c interruption
signal.signal(signal.SIGINT, lambda x, y: sim.stop())

# Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator')
# This will be address in the simulation network
allocator.local = "{}:5555".format(net_addr[0])
# Hit Agent's run, from here on scheduled events will be executed
# if local address is not set at initialization or before run,
# an exception is raised
initial_time = time()
allocator.run()
# Hook a callback to receive notifications of reported allocations
allocator.allocation_updated = allocation_updated

# Create empty panda power network that will be filled later
# create pandapower network
net = pp.create_empty_network()
net = create_pp_net(net)
create_nodes(sim)

fig = plt.figure()
ax = fig.add_subplot(1, 1, 1)
xs = list()  # type:List
ys = list()  # type:List


def animate(i, xs, ys):
    timestamp, name, p_kw, q_kw = allocations_queue.get()
    print("\n\n{}: P, Q = {}, {}".format(name, p_kw, q_kw))
    net.load.loc[net.load['name'] == name, 'p_kw'] = p_kw
    net.load.loc[net.load['name'] == name, 'q_kw'] = q_kw
    pp.runpp(net)
    vm_pu = net.res_bus.loc[1, 'vm_pu']
    print("\n\n\nVotage:\n{}\n\n\n".format(vm_pu))
    # Add x and y to lists
    xs.append(timestamp - initial_time)
    ys.append(vm_pu)

    # Limit x and y lists to 20 items
    xs = xs[-20:]
    ys = ys[-20:]

    # Draw x and y lists
    ax.clear()
    ax.plot(xs, ys)

    # Format plot
    plt.xticks(rotation=45, ha='right')
    plt.subplots_adjust(bottom=0.30)
    plt.title('Voltage value over Time')
    plt.ylabel('voltage value (p.u.)')


ani = animation.FuncAnimation(fig, animate, fargs=(xs, ys), interval=1000)
plt.show()
