from sens import SmartGridSimulation
import signal


## Used localy to load and prepare data
def load_csv(file, columns=[]):
    import pandas as pd
    # Data prepation
    curves = pd.read_csv(file)
    filtered = curves.filter(items=columns).values.tolist()
    return filtered

## to be used remotely to implement node's consumption behavior
def func(node, loads):
    # put remote imports in function body
    # to make sure import is executed remotely
    from sens import Allocation
    # Scheduling allocation
    for v in loads:
        allocation = Allocation(0, v[1], v[2])
        node.schedule(
                action=node.allocation_handle, 
                args={'allocation':allocation}, 
                delay=v[0])
        node.schedule(
                action=node.allocation_report, 
                delay=v[0])

## Create SmartGridSimulation environment
sim = SmartGridSimulation()

signal.signal(signal.SIGINT, lambda x, y: sim.stop())

ipv4s=['10.10.10.1','10.10.10.98','10.10.10.110','10.10.10.94','10.10.10.36','10.10.10.45']

## Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator')
## This will be address in the simulation network
allocator.local = "{}:5555".format(ipv4s[0])
## Hit Agent's run, from here on scheduled events will be executed
allocator.run()

## Create remote agents of type NetworkLoad
for i in range(5):
    node = sim.create_remote_node(
        hostname=ipv4s[i+1], username='ubuntu', keyfile='~/.ssh/id_rsa.pub')
    ## This will be address in the simulation network
    node.local = "{}:5000".format(ipv4s[i+1])
    node.run()
    node.send_join("{}:5555".format(ipv4s[0]))

for i in range(5):
    f = sim.teleport(sim.conns[i], func)
    sim.conns[i].namespace['func'] = f
    loads = load_csv('victor_scripts/curves.csv', ['timestamp','load_%d_p'%(i+1), 'load_%d_q'%(i+1)])
    loads = sim.deliver(sim.conns[i], loads)
    sim.conns[i].namespace['loads'] = loads
    sim.conns[i].execute("func(node, loads)")
    f(sim.nodes[i+1], loads)