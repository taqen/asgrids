from rpyc.utils.zerodeploy import DeployedServer
import rpyc
from plumbum import SshMachine, local
from plumbum.path.utils import copy
import network_agent

class SmartGridSImulation:
    def __init__(self):
        self.nodes = []
        self.conns = []
    def _init_remote(self, hostname, username, keyfile):
        remote_machine = SshMachine(host=hostname, user=username, keyfile=keyfile)
        remote_server = DeployedServer(remote_machine)
        conn = remote_server.classic_connect()
        rpyc.classic.upload_module(
            conn, 
            network_agent, 
            "/home/ubuntu/.local/lib/python3.6/site-packages/")

    def create_node(self, hostname, username, keyfile, ntype='load', config={}):
        remote_machine = SshMachine(host=hostname, user=username, keyfile=keyfile)
        remote_server = DeployedServer(remote_machine)
        remote_tmp = remote_server.proc.argv[8]
        remote_tmp = remote_machine.path(remote_tmp).up()
        for f in [
            "network_load.py", 
            "network_allocator.py", 
            "agent.py", 
            "defs.py",
            "async_communication.py"
            ]:
            copy(local.cwd // f, remote_tmp)
        conn = remote_server.classic_connect()
        self.conns.append(conn)
        conn.execute('from network_load import NetworkLoad')
        node = conn.eval("NetworkLoad()")
    
    def run(self):

