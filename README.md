
# Table of Contents

0. [Generating/Processing results for APPEEC'19](#appeec)
    1. [Performance Measurements](#perf)
    2. [CIGRE LV scenario](#cigre)
1.  [Preliminary Architecture](#org023c124)
    1.  [The Generic Agent](#orgc72bd4a)
    2.  [The Allocator Agent](#orgccb2621)
    3.  [The Network Load Agent](#org750e490)
    4.  [Smart Grid Simulation](#sgsim)
<a id="org023c124"></a>

<a id="appeec"></a>
# Generating/Processing results for APPEEC'19
The results for APPEEC consists of performance/scalability measurements, and a use case scenario.
<a id="perf"></a>
## Performance Measurements
We perform CPU/MEM measurements by running the script in `./examples/large_grid_example`, using [`psrecord`](https://github.com/astrofrog/psrecord) to log realtime CPU and memory usage, with different network sizes as follows:
```bash
for i in 10 20 50 100 300 500 1000; do psrecord --include-children --log ps.${i}.out "python large_grid_example.py --pp --sim-time 30 --pp-cycle 0 --case case300 --nodes $i"; done
```
To generate the plot, we run the script `./examples/plot_memory.py` in the same folder as the generated results.

**Note**

This script assumes that the results are stored in the same folder in the format above

<a id="cigre"></a>
## CIGRE LV scenario
The scenario is implemented in simulation script `./examples/cigre_pv_example.py`.
The script will deploy a CIGRE LV network as implemented in `pandapower`, along with a power flow analyzer and optimal power flow solver as described in our paper.
To run multiple simulation campaigns, the script is executed as follows:
```bash
for run in 1 2 3 4 5 6 7 8 9 10; do for address in "127.0.0.1" "127.0.2.1" "127.0.3.1" "127.0.4.1" "127.0.5.1"; do for mode in "tcp" "udp"; do taskset -c 0 python cigre_pv_example.py --initial-port 5000 --with-pv --optimize --optimize-cycle 3 --optimizer opf --address $address --max-vm 1.05 --mode $mode --output "./results/${mode}/sim.${optimizer}.${address}loss.${run}.log"; done; done;done
```
Assuming that local interfaces: 127.0.0.1, 127.0.2.1, 127.0.3.1, 127.0.4.1, 127.0.5.1 are configure with `netem` through `./examples/create_netem.sh` to exhibit the packet losses: 0%, 10%, 20%, 30%, 60% consecutively.

Plotting the results will rely on two scripts: 
    1. `./examples/plot_loss_com.py`: to generate voltage violates per packet loss rate figure.
    The figures in the paper are generated with this configuration:
    ```bash
    python plot_loss_com.py --runs 1 2 3 4 5 6 7 8 9 10 --losses 0 10 20 30 60 --output bars_loss.png --results ./results/ --width 0.5 --figsize 8 4
    ```
    2. `./examples/plot_prod_com.py`: to generate production loss rate per packet loss rate figure.
    The figures in the paper are generated with this configuration:
    ```bash
    python plot_prod_com.py --runs 1 2 3 4 5 6 7 8 9 10 --losses 0 10 20 30 60 --output bars_loss.png --results ./results/ --width 0.5 --figsize 8 4
    ```
    
    
It is possible to save the process data for quick reuse to tune/tweak the plot, by provided `--save data.pkl` during a first run, the loading with `--load data.pkl` in later runs. Runs, losses and figure size can also be selected and plotted individually or in any configuration by playing the scripts arguments.

**Note**

These two scripts assume that the results are stored in `./results/tcp` and `./results/udp` for tcp and udp data consecutively, in the format used above.

# Preliminary Architecture

In order to model the operation of a smart grid, the simulator needs to operates asynchronously on a distributed architecture.
As a consequence a multi-agent design paradigm is probably a good way to describe it.


<a id="orgc72bd4a"></a>
## The Generic Node

The generic agent translates to the basic class the implements the basic behavior of running an endless event loop, and processing actions as they are scheduled.
The Agent interacts with the outside world through AsyncComms interface. This interface is implmented through various child classes the inherit from the Agent.
The interaction between the scheduling and AsyncComms interface is as can be seen in <a id="orgca9be06"></a>.
The code block bellow shows an implementation of such an Agent.

    class Node:
      """ A generic Network Node.
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
```bash
python3 setup.py build
python3 setup.py install
cd examples
python smart_grid_example.py
```
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
