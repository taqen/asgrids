from collections import namedtuple

class Allocation(namedtuple('Allocation', ['id', 'value', 'duration'])):
    def __new__(cls, id=0, value=0, duration=0):
        return super(Allocation, cls).__new__(cls, id, value, duration)

class Packet(namedtuple('Packet', ['ptype', 'payload', 'src'])):
    def __new__(cls, ptype, payload=None, src=None):
        packet_types = ['allocation', 'curr_allocation', 'join', 'join_ack', 'allocation_ack', 'stop', 'stop_ack', 'leave', 'leave_ack']
        if ptype not in packet_types:
            raise ValueError('Undefined packet type {}'.format(ptype))
        if ptype in ['allocation', 'curr_allocation']:
            assert isinstance(payload, Allocation), 'Packet type "allocation" needs an allocation payload not a {}'.format(type(payload))
        return super(Packet, cls).__new__(cls, ptype, payload, src)