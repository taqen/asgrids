
# Table of Contents

1.  [Preliminary Architecture](#org023c124)
    1.  [The Generic Agent](#orgc72bd4a)
    2.  [The Allocator Agent](#orgccb2621)
    3.  [The Network Load Agent](#org750e490)
    4.  [Smart Grid Simulation](#sgsim)
<a id="org023c124"></a>

# Preliminary Architecture

In order to model the operation of a smart grid, the simulator needs to operates asynchronously on a distributed architecture.
As a consequence a multi-agent design paradigm is probably a good way to describe it.


<a id="orgc72bd4a"></a>

## The Generic Agent

The generic agent translates to the basic class the implements the basic behavior of running an endless event loop, and processing actions as they are scheduled.
The Agent interacts with the outside world through AsyncComms interface. This interface is implmented through various child classes the inherit from the Agent.
The interaction between the scheduling and AsyncComms interface is as can be seen in <a id="orgca9be06"></a>.
The code block bellow shows an implementation of such an Agent.

    class Agent:
      """ A generic Network Agent.
      """
      def __init__(self, env=None):
        if env is None:
          self.env = simpy.Environment()
        else:
          self.env = env
        self.stop = False
        self.env.process(self.run())
        self.env.run()
    
      def run(self):
        while not self.stop:
          #self.env.process(self.run)
          yield self.env.timeout(10)
    
      def schedule(self, time, action):
        """ generates a production/consumption event
        """
        p = self.env.process(action, delay=time)
        return p
    
      def stop(self):
        self.stop = True


<a id="orgccb2621"></a>

## The Allocator Agent

Contains the standard facilities of Scheduling and Communicating, wrapped around simpy and AsyncCommunication.
The allocator doesn't consume or produce per se, but generates production and consumption profiles corresponding for network elements (generators, loads &#x2026; etc).
The class definition is bellow

    class NetworkAllocator(Agent):
      """ Simulate a communicating policy allocator
      """
      def __init__(self, local='*:5555'):
        self.loads = {}
        self.comm = AsyncCommunication()
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        self.local = local
        super(NetworkAllocator, self).__init__()
    
      def initlise(self):
        pass
    
      def receive_handle(self, data, src):
        pass
      def add_load(self, load):
        self.loads[load['id']] = load
    
      def remove_load(self, id):
        self.loads.popitem(id)
    
      def send_allocation(self, id , allocation):
        self.schedule(action = send_allocation(id, allocation))
    
      def stop(self):
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkAllocator, self).stop())


<a id="org750e490"></a>

## The Network Load Agent

The Network Load models the behavior of an Agent that can handle Allocator commands to consume/produce specific allocations.
It inherits from the Generic Agents and interfaces with the outside world through the AsyncCommunication class.

    class NetworkLoad(Agent):
      def __init__(self, remote='127.0.0.1:5555', local='*:5000'):
        self.remote = remote
        self.local = local
        self.id=self.local
        self.comm = AsyncCommunication(identity=self.id)
        self.comm.run_server(callback=self.receive_handle, local_address=local)
        self.comm.start()
        super(NetworkLoad, self).__init__()
    
      def receive_handle(self, data, src):
        msg_type = data['msg_type']
        if msg_type == 'ack':
          return
        if msg_type == 'allocation':
          allocation = data['allocation']
          duration = data['duration']
          self.schedule(time=0, action=send_ack(allocation, dst=src))
          self.schedule(time=0, action=allocation_handle(allocation, duration))
    
      def allocation_handle(self, allocation, duration):
        yield self.env.timeout(duration)
    
      def join_ack_handle(self):
        pass
    
      def send_join(self):
        packet={'msg_type':'join', 'id':self.id}
      def send_ack(self, allocation):
        packet={"allocation_id" : allocation['allocation_id'], "msg_type": "allocation_ack"}
        self.comm.send(packet, remote=self.remote)
    
      def stop(self):
        self.env.process(self.comm.stop())
        self.env.process(super(NetworkLoad, self).stop())

<a id="sgsim"></a>
## Smart Grid Simulation
SENS implements a SmartGridSimulation class in ```deploy.py```. This class is responsible of creating remote and local nodes to build our co-simulation communication network topology.

Agents will be deployed remotely if needed and interfaced locally to provide a unified environemnt where we can dynamically interact with our ongoing co-simulation in realtime.

In this example (```examples/smart_grid_example.py```) the power network in the figure bellow is implemented in pandapower, than a corresponding SmartGridSimulation physical (virtual) network is created to model the realtime behavior of clients (1-5).

Each clients will replay a recorded timeseries of allocations that is provided by ```victor_scripts/curves.csv```. No PV capabilities are modeled for now.
![pandapower topology](victor_scripts/topology.png?raw=true "pandapower topology")

In ```smart_grid_example.py```, there are three key steps in the simulation:
### Electrical Network Setup
Using pandapower we implement a simple 5-client topology as described in the figure above.

```python
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
```
### Communication Network Setup
We provide our network addresses topology in net_addr.

```python
net_addr=['10.10.10.1','10.10.10.98','10.10.10.110','10.10.10.94','10.10.10.36','10.10.10.45']
```
Addresses in this case correspond to already created lxc containers. Each container will received a NetworkLoad instance that will run to model a specific client's power consumption/production behavior as defined by the corresponding csv table.

```python
node, conn = sim.create_remote_node(
    hostname=net_addr[i+1], username='ubuntu', keyfile='~/.ssh/id_rsa.pub')
## This will be address in the simulation network
## "node" is already registered in remote namespace
conn.execute("node.local = '{}:5000'".format(net_addr[i+1]))
## Runs the remote node
conn.execute("node.run()")
## Schedules a join request to join the allocator
conn.execute("node.schedule(node.send_join, {{'dst':'{}:5555'}})".format(net_addr[0])) 
```
### Communication/Power network synchronization
Synchronization is needed to update the pandapower net with new p/q values as reported by network clients.
Then we run a power flow analysis to determin realtime voltage value on the bus.
To achieve this, NetworkAllocator allows registering a callback that will be called each time a new allocation is received from a client.
```python
allocations_queue = Queue()
def allocation_updated(allocation, node_addr):
    ## We receive node_addr as "X.X.X.X:YYYY"
    ## ind also identifies the node in pandapawer loads list
    ind = net_addr.index(node_addr.split(":")[0])
    ## Don't block here just push to a queue and return
    allocations_queue.put(["Load_{}".format(ind), allocation.p_value, allocation.q_value])

allocator.allocation_updated = allocation_updated
```
In this way the script defied allocation_updated will be called by the NetworkAllocator. It will then, queue the new values in a Queue() to avoid blocking the execution of the allocator execution loop.

The queued values will be read by a ```python while``` loop that will updated pandapower net and runs the powerflow analysis.
```python
while True:
    name, p_kw, q_kw = allocations_queue.get()
    print("\n\n{}: P_KW, Q_KW = {}, {}".format(name, p_kw, q_kw))
    net.load.loc[net.load['name'] == name, 'p_kw'] = p_kw
    net.load.loc[net.load['name'] == name, 'q_kw'] = q_kw
    pp.runpp(net)
    voltage_values.append(net.res_bus.loc[1, 'vm_pu'])
    print("\n\nUPDATED VOLTAGE VALUE\n{}\n\n".format(net.res_bus.loc[1, 'vm_pu']))
    
```
### Configuring LXC containers for smart_grid_example.py
```bash
sudo lxd init
lxc network edit lxdbr0 # if configured lxc bridge is lxdbr0, then setup address space desired for the containers
lxc launch ubuntu:18.04 node1
# if priviliged containers error use this instead
lxc launch ubuntu:18.04 node1 -c security.privileged=true -c security.nesting=true
# log to container
lxc exec node -- sudo --login --user ubuntu
# install python3 and related dependencies
sudo apt install python3.6 python-pip
pip install zmq simpy plumbum msgpack
#logout
exit
# copy container to create the other ones
lxc copy node1 node2 && lxc copy node1 node2 && lxc copy node1 node4 && lxc copy node1 node5
# to list containers with their IPv4 address
lxc list

```
```
