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
from queue import Empty, Full
from queue import Queue
from sens import SmartGridSimulation
from sens import Allocation
import tracemalloc
import os
import linecache

def display_top(snapshot, key_type='lineno', limit=10):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    top_stats = snapshot.statistics(key_type)

    print("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        # replace "/path/to/module/file.py" with "module/file.py"
        filename = os.sep.join(frame.filename.split(os.sep)[-2:])
        print("#%s: %s:%s: %.1f KiB"
              % (index, filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            print('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        print("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    print("Total allocated size: %.1f KiB" % (total / 1024))
def monitor_memory(N):
    tracemalloc.start()
    while i in range(N):
        tracemalloc.start()
        snapshot = tracemalloc.take_snapshot()
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('traceback')
        stat = top_stats[0]
        print("%s memory blocks: %.1f KiB" % (stat.count, stat.size / 1024))
        for line in stat.traceback.format():
            print(line)
        sleep(1.0)
    tracemalloc.stop()

#%%
allocations_queue: Queue = Queue()
measure_queues: dict = {}
network_size: Queue = Queue()
plot_values: Queue = Queue()
## Create SmartGridSimulation environment
sim = SmartGridSimulation()
#%%
# generate sequential port numbers
def gen_port(initial_port):
    port = initial_port
    while True:
        yield port
        port = port+1

def joined_network(src, dst):
    # print("{} joined network".format(src))
    network_size.put(src)

## Used localy to load and prepare data
def load_csv(file, columns=[]):
    import pandas as pd
    # Data prepation
    curves = pd.read_csv(file)
    filtered = curves.filter(items=columns).values.tolist()
    return filtered

## This is an example of how to schedule events from a generated timeseries
def generate_allocations(node, old_allocation):
    # Scheduling allocations
    try:
        new_allocation = Allocation(
            aid=0,
            p_value=old_allocation.p_value*(1+random.uniform(-1e-1, 1e-1)), 
            q_value=old_allocation.q_value*(1+random.uniform(-1e-1, 1e-1)),
            duration=random.uniform(1, 60))
        return new_allocation
    except Exception as e:
        print(e)

def allocation_updated(allocation: Allocation, node_addr: str):
    ## We receive node_addr as "X.X.X.X:YYYY"
    ## ind also identifies the node in pandapawer loads list
    # print("received allocation update")
    allocations_queue.put([time(), node_addr, allocation.p_value, allocation.q_value])
    try:
        res = measure_queues[node_addr].get_nowait()
    except Empty:
        res = None
    return res

def create_nodes(net, remote):
    ## Create remote agents of type NetworkLoad
    nodes = []
    for i in range(len(net.load.index)):
        node = sim.create_node('load', '127.0.0.1:{}'.format(next(port)))
        node.run()
        measure_queues[node.local] = Queue(maxsize=1)
        node.update_measure = allocation_updated
        node.joined_callback=joined_network
        node.generate_allocations = generate_allocations
        net.load['name'][i] = "{}".format(node.local)
        nodes.append(node)

    for node in nodes:
        node.schedule(node.send_join, {'dst':'{}'.format(remote)})
    return nodes

## Handle ctrl-c interruptin
def shutdown(x, y):
    allocations_queue.put([0,0,0,0])
    sim.stop()
signal.signal(signal.SIGINT, shutdown)

port = gen_port(5555)

#%%
## Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator', addr="127.0.0.1:{}".format(next(port)))
## Hit Agent's run, from here on scheduled events will be executed
## if local address is not set at initialiazion or before run, 
## an exception is raised
initial_time = time()
allocator.run()

#%%
## Create a corresponding multi-agent deployment to the pandapower network
net = pn.case6ww()
nodes = create_nodes(net, allocator.local)

def runpp():
    while not sim.shutdown:
        try:
            qsize = allocations_queue.qsize()
            # print("runpp: updating {} new allocations".format(qsize))
            for i in range(qsize):
                timestamp, name, p_kw, q_kw = allocations_queue.get()
                if timestamp == 0:
                    break
                net.load.loc[net.load['name'] == name, 'p_kw'] = p_kw
                net.load.loc[net.load['name'] == name, 'q_kw'] = q_kw
        except Exception as e:
            print(e)
        converged = True
        try:
            pp.runpp(net, init_vm_pu='results')
            # print("Finished runpp")
            converged = True
        except Exception as e:
            print(e)
            converged = False

        # Updating voltage measures for clients and live_plot
        if converged:
            for node in measure_queues:
                bus_ind = net.load['bus'][net.load['name'] == node].item()
                vm_pu = 0
                vm_pu = net.res_bus['vm_pu'][bus_ind].item()
                try:
                    measure_queues[node].put_nowait(vm_pu)
                except Full:
                    measure_queues[node].get()
                    measure_queues[node].put(vm_pu)
                # print("\nVotage at bus {}: {}\n".format(bus_ind, vm_pu))
            try:
                for row in net.res_bus.iterrows():
                    plot_values.put([time(), row[0], row[1][0].item()])
            except Exception as e:
                print(e)

#%%
def live_plot():
    fig = plt.figure()
    ax = fig.add_subplot(1, 1, 1)
    xs = {}
    ys = {}
    for row in net.bus.iterrows():
        xs[row[0]]=[]
        ys[row[0]]=[]
    
    def animate(i, xs, ys):
        qsize = plot_values.qsize()
        for _ in range(qsize):
            timestamp, bus_id, value = plot_values.get()
            # Add x and y to lists
            try:
                xs[bus_id].append(timestamp-initial_time)
                ys[bus_id].append(value)
            except Exception as e:
                print("Exception when filling xs, ys {}".format(e))    
            # Limit x and y lists to 20 items
            xs[bus_id] = xs[bus_id][-20:]
            ys[bus_id] = ys[bus_id][-20:]
            # Draw x and y lists
        try:
            ax.clear()
            for bus_id in xs:
                ax.plot(xs[bus_id], ys[bus_id], label="bus {}".format(bus_id))
        except Exception as e:
            print("Exception when plotting {}".format(e))
        # Format plot
        ax.legend()
        plt.xticks(rotation=45, ha='right')
        plt.subplots_adjust(bottom=0.30)
        plt.title('Voltage value over Time')
        plt.ylabel('voltage value (p.u.)')

    ani = animation.FuncAnimation(fig, animate, fargs=(xs, ys), interval=20)
    plt.show()

#%%
print("waiting for Network ready: {}".format(len(nodes)))
while network_size.qsize() < len(nodes):
    continue
print("Network ready")
for node in nodes:
    allocation = Allocation(
        0, 
        net.load[net.load['name']==node.local]['p_kw'].item(), 
        net.load[net.load['name']==node.local]['q_kvar'].item(), 
        1)
    node.handle_allocation(allocation)

#%%
with Executor(max_workers=200) as executor:
    executor.submit(runpp)
    live_plot()
    # executor.submit(monitor_memory, 5)

