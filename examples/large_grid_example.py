#%%
import signal
import pandapower as pp
import pandapower.networks as pn
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy
import random
import asyncio
from concurrent.futures import ThreadPoolExecutor as Executor
from time import time, sleep
from queue import Queue, Empty
from sens import SmartGridSimulation
from sens import Allocation

#%%
# generate sequential port numbers
def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port+1
port = gen_port(5555)

allocations_queue: Queue = Queue(1000)
measure_queues: dict = {}
network_size: Queue = Queue()
## Create SmartGridSimulation environment
sim = SmartGridSimulation()
## Handle ctrl-c interruptin
def shutdown(x, y):
    allocations_queue.put([0,0,0,0])
    sim.stop()

signal.signal(signal.SIGINT, shutdown)

#%%
def joined_network(src, dst):
    print("{} joined network".format(src))
    network_size.put(src)

## Used localy to load and prepare data
def load_csv(file, columns=[]):
    import pandas as pd
    # Data prepation
    curves = pd.read_csv(file)
    filtered = curves.filter(items=columns).values.tolist()
    return filtered

## This is an example of how to schedule events from a generated timeseries
def generate_allocations(node):
    # Scheduling allocations
    while True:
        if node.remote is None:
            print("Node {} didn't join network yet".format(node.local))
            break
        allocation = Allocation(0, random.uniform(5e3,6e3), random.uniform(5e3,6e3))
        node.schedule(action=node.allocation_handle, 
            args={'allocation':allocation},
            delay=1,
            callbacks=[node.allocation_report])

def allocation_updated(allocation: Allocation, node_addr: str):
    ## We receive node_addr as "X.X.X.X:YYYY"
    ## ind also identifies the node in pandapawer loads list
    print("received allocation update")
    allocations_queue.put([time(), "Load_{}".format(node_addr), allocation.p_value, allocation.q_value])
    try:
        res = measure_queues[node.local].get_nowait()
    except Empty:
        res = 0
    return res

def create_nodes(net, remote):
    ## Create remote agents of type NetworkLoad
    nodes = []
    for i in range(len(net.load.index)):
        node = sim.create_node()
        node.local = '127.0.0.1:{}'.format(next(port))
        node.run()
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure = allocation_updated
        node.joined_callback=joined_network
        net.load['name'][i] = "Load_{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst':'{}'.format(remote)})
    return nodes


#%%
## Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator')
## This will be address in the simulation network
allocator.local = "127.0.0.1:{}".format(next(port))
## Hit Agent's run, from here on scheduled events will be executed
## if local address is not set at initialiazion or before run, 
## an exception is raised
initial_time = time()
allocator.run()

#%%
## Create empty panda power network that will be filled later
# create pandapower network
net = pn.panda_four_load_branch()
nodes = create_nodes(net, allocator.local)
plot_values: Queue = Queue()

def runpp():
    while True:
        qsize = allocations_queue.qsize()
        for i in range(qsize):
            timestamp, name, p_kw, q_kw = allocations_queue.get()
            if timestamp == 0:
                break  
            net.load.loc[net.load['name'] == name, 'p_kw'] = p_kw
            net.load.loc[net.load['name'] == name, 'q_kw'] = q_kw
        converged = True
        try:
            pp.runpp(net)
            print("Finished runpp")
            converged = True
        except Exception as e:
            print(e)
            converged = False

        for name, q in measure_queues:
            bus_ind = net.load.loc[net.load['name'] == name]['bus']
            vm_pu = 0
            if converged:
                vm_pu = net.res_bus.loc[bus_ind]['vm_pu'].item()
            q.put(vm_pu)
            print("\nVotage at bus {}: {}\n".format(bus_ind, vm_pu))

#%%
def live_plot():
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    xs :list = []
    ys :list = []

    def animate(i, xs, ys):
        timestamp, value = plot_values.get()
        # Add x and y to lists
        xs.append(timestamp-initial_time)
        ys.append(value)

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


#%%
print("waiting for Network ready: {}".format(len(nodes)))
while network_size.qsize() < len(nodes):
    sleep(1)
print("Network ready")

#%%
with Executor(max_workers=200) as executor:
    # executor.submit(live_plot)
    executor.submit(runpp)
    for node in nodes:
        executor.submit(generate_allocations, node)
