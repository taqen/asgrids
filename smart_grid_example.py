from sens import SmartGridSimulation
sim = SmartGridSimulation()

allocator = sim.create_node(ntype='allocator')
## This will be address in the simulation network
allocator.local = "10.222.247.1:5555"
allocator.run()

remote_node = sim.create_remote_node(
    hostname='10.222.247.98', username='ubuntu', keyfile='~/.ssh/id_rsa.pub')
## This will be address in the simulation network
remote_node.local = "10.222.247.98:5000"
remote_node.run()
remote_node.send_join("10.222.247.1:5555")
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
        allocation = Allocation(0, v[1], 0)
        node.schedule(
                action=node.allocation_handle, 
                args={'allocation':allocation}, 
                delay=v[0])
        node.schedule(
                action=node.allocation_report, 
                delay=v[0])
