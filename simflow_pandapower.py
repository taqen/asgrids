import pandapower as pp
import numpy as np
net = pp.create_empty_network()

#create buses
bus1 = pp.create_bus(net, vn_kv=220.)
bus2 = pp.create_bus(net, vn_kv=110.)
bus3 = pp.create_bus(net, vn_kv=110.)
bus4 = pp.create_bus(net, vn_kv=110.)

#create 220/110 kV transformer
pp.create_transformer(net, bus1, bus2, std_type="100 MVA 220/110 kV")

#create 110 kV lines
pp.create_line(net, bus2, bus3, length_km=70., std_type='149-AL1/24-ST1A 110.0')
pp.create_line(net, bus3, bus4, length_km=50., std_type='149-AL1/24-ST1A 110.0')
pp.create_line(net, bus4, bus2, length_km=40., std_type='149-AL1/24-ST1A 110.0')

#create loads
pp.create_load(net, bus2, p_kw=60e3, controllable = False)
pp.create_load(net, bus3, p_kw=70e3, controllable = False)
pp.create_load(net, bus4, p_kw=100e3, controllable = False)

#create generators
eg = pp.create_ext_grid(net, bus1)
g0 = pp.create_gen(net, bus3, p_kw=-80*1e3, min_p_kw=-80e3, max_p_kw=0,vm_pu=1.01, controllable=True)
g1 = pp.create_gen(net, bus4, p_kw=-100*1e3, min_p_kw=-100e3, max_p_kw=0, vm_pu=1.01, controllable=True)
costeg = pp.create_polynomial_cost(net, 0, 'ext_grid', np.array([1, 0]))
costgen1 = pp.create_polynomial_cost(net, 0, 'gen', np.array([1, 0]))
costgen2 = pp.create_polynomial_cost(net, 1, 'gen', np.array([1, 0]))

pp.runopp(net, verbose=True)

print(net.res_gen)
