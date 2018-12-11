from rpyc.utils.zerodeploy import DeployedServer
import rpyc
from rpyc.utils.helpers import BgServingThread
from plumbum import SshMachine, local
from plumbum.path.utils import copy
import agent
import network_load
import network_allocator
import defs
import async_communication

class SmartGridSimulation:
    def __init__(self):
        self.nodes = []
        self.conns = []
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []
    def _init_remote(self, remote_server, ntype='load'):
        conn = remote_server.classic_connect()
        rpyc.classic.upload_module(
            conn,
            agent,
            "/home/ubuntu/.local/lib/python3.6/site-packages/")
        rpyc.classic.upload_module(
            conn,
            network_load,
            "/home/ubuntu/.local/lib/python3.6/site-packages/")
        rpyc.classic.upload_module(
            conn,
            network_allocator,
            "/home/ubuntu/.local/lib/python3.6/site-packages/")
        rpyc.classic.upload_module(
            conn,
            async_communication,
            "/home/ubuntu/.local/lib/python3.6/site-packages/")
        rpyc.classic.upload_module(
            conn,
            defs,
            "/home/ubuntu/.local/lib/python3.6/site-packages/")

    def create_node(self, hostname, username, keyfile, ntype='load', config={}):
        remote_machine = SshMachine(host=hostname, user=username, keyfile=keyfile)
        remote_server = DeployedServer(remote_machine)
        self._init_remote(remote_server)
        remote_server.close()
        remote_server = DeployedServer(remote_machine)
        self.remote_machines.append(remote_machine)
        self.remote_servers.append(remote_server)
        remote_tmp = remote_server.proc.argv[8]
        remote_tmp = remote_machine.path(remote_tmp).up()
        conn = remote_server.classic_connect()
        serving_thread = BgServingThread(conn)
        self.server_threads.append(serving_thread)
        self.conns.append(conn)
        node = None
        if ntype is 'load':
            node = conn.modules.network_load.NetworkLoad(local="{}:5000".format(hostname))
        elif ntype is 'allocator':
            node = conn.modules.network_allocator.NetworkAllocator(local="{}:5555".format(hostname))
        else:
            raise ValueError("Can't handle ntype == {}".format(ntype))
        self.nodes.append(node)
        return node
    
    def run(self):
        for node in self.nodes:
            node.run()

    def get_node(self, ind):
        return self.nodes[ind]

    def stop(self):
        for node in self.nodes:
            node.stop()
        for server in self.remote_servers:
            server.close()
        for thread in self.server_threads:
            thread.close()
        self.node = []
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []
