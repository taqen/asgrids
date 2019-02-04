from rpyc.utils.zerodeploy import DeployedServer
import rpyc
from rpyc.utils.helpers import BgServingThread
from rpyc.utils.classic import teleport_function, deliver
from plumbum import SshMachine, local
from plumbum.path.utils import copy
import typing
import sens
from sens import NetworkAllocator, NetworkLoad


"""
This defines a smart grid simulation environment
It handles deployement/execution of local and remote nodes
"""
class SmartGridSimulation:
    def __init__(self):
        self.nodes = {}
        self.conns = {}
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []

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
    Make sure 'sens' library is available remotely
    """
    def check_remote(self, remote_server, python_pkg_path="/home/ubuntu/.local/lib/python3.6/site-packages/"):
        conn = remote_server.classic_connect()
        import os
        rpyc.classic.upload_package(
            conn,
            sens,
            os.path.join(python_pkg_path, "sens"))
        return False

    """
    Create node with type 'ntype' on the remote machine `hostname`
    Returns a rpyc object wrapper, that enables handling the remote object
    as if it was created locally.
    """
    def create_remote_node(self, hostname, username, keyfile, ntype, addr, config={}):
        remote_machine = SshMachine(host=hostname, user=username, keyfile=keyfile)
        remote_server = DeployedServer(remote_machine)
        # if `sens` wasn't available remotely, now we installed it
        # but we need to reconnect to get an updated conn.modules
        # TODO Might not be needed if using execute/eval
        if not self.check_remote(remote_server):
            remote_server.close()
            remote_server = DeployedServer(remote_machine)

        self.remote_machines.append(remote_machine)
        self.remote_servers.append(remote_server)
        conn = remote_server.classic_connect()
        serving_thread = BgServingThread(conn)
        self.server_threads.append(serving_thread)
        self.conns[addr]=conn
        node = None

        ## Using execute/eval allows working on a remote single namespace
        ## useful when teleporting functions that need using remote object names
        ## as using conn.modules create a locate but not a remote namespace member
        if ntype is 'load':
            conn.execute("from sens import NetworkLoad")
            conn.execute("node=NetworkLoad()")
            conn.execute("node.local={}".format(addr))
            node = conn.namespace['node']
        elif ntype is 'allocator':
            conn.execute("from sens import NetworkAllocator")
            conn.execute("node=NetworkAllocator()")
            node = conn.namespace['node']
        else:
            raise ValueError("Can't handle ntype == {}".format(ntype))
        self.nodes[addr]=node

        ## Return node netref object and rpyc connection
        return node, conn


    """
    Creates a local node
    """
    def create_node(self, ntype, addr):
        if ntype is 'load':
            node = NetworkLoad()
            node.local = addr
            self.nodes[addr] = node
            return node
        elif ntype is 'allocator':
            node = NetworkAllocator()
            node.local = addr
            self.nodes[addr] = node
            return node
    """
    Runs the created remote objects
    """
    def run(self):
        for node in self.nodes:
            node.run()

    def get_node(self, ind):
        return self.nodes[ind]

    """
    Stops the remotely created nodes
    """
    def stop(self):
        # for node in self.nodes:
        #     node.stop()
        for _, node in self.nodes.items():
            node.stop()
        for server in self.remote_servers:
            server.close()
        self.node = {}
        self.remote_machines = []
        self.remote_servers = []
        self.server_threads = []
        self.shutdown = True