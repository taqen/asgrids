from sens import SmartGridSimulation
from sens import Allocation
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
    # Scheduling allocation
    for v in loads:
        allocation = Allocation(0, v[1], v[2])
        node.schedule(action=node.allocation_handle, 
            args={'allocation':allocation}, 
            delay=v[0], 
            callbacks=[node.allocation_report])

## Create SmartGridSimulation environment
sim = SmartGridSimulation()

signal.signal(signal.SIGINT, lambda x, y: sim.stop())

## Create a local Agent of type NetworkAllocator
allocator = sim.create_node(ntype='allocator')
## This will be address in the simulation network
allocator.local = "127.0.0.1:5555"
## Hit Agent's run, from here on scheduled events will be executed
allocator.run()

## Create remote agents of type NetworkLoad
node = sim.create_node(ntype='load')
node.local="127.0.0.1:5000"
node.run()
node.schedule(node.send_join, {'dst':'127.0.0.1:5555'})

loads = load_csv('../victor_scripts/curves.csv', ['timestamp','load_1_p', 'load_1_q'])
func(node, loads)