#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandapower as pp
import pandas as pd
from matplotlib import pyplot as plt

# create pandapower network
net = pp.create_empty_network()
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
pp.to_json(net, 'electrical_network.json')

# load flow
curves = pd.read_csv('curves.csv')
voltage_values = {'without_pv': [], 'with_pv': []}
for index, row in curves.iterrows():
    # without PV
    for i in range(5):
        net.load.loc[net.load['name'] == "Load_{}".format(i + 1), 'p_kw'] = row['load_{}_p'.format(i + 1)]
        net.load.loc[net.load['name'] == "Load_{}".format(i + 1), 'q_kvar'] = row['load_{}_q'.format(i + 1)]
        net.load.loc[net.load['name'] == "PV_{}".format(i + 1), 'p_kw'] = 0
        net.load.loc[net.load['name'] == "PV_{}".format(i + 1), 'q_kvar'] = 0
    pp.runpp(net)
    voltage_values['without_pv'].append(net.res_bus.loc[1, 'vm_pu'])
    # with PV
    for i in range(5):
        net.load.loc[net.load['name'] == "PV_{}".format(i + 1), 'p_kw'] = row['pv_{}_p'.format(i + 1)]
        net.load.loc[net.load['name'] == "PV_{}".format(i + 1), 'q_kvar'] = row['pv_{}_q'.format(i + 1)]
    pp.runpp(net)
    voltage_values['with_pv'].append(net.res_bus.loc[1, 'vm_pu'])

# display
figure = plt.figure()
ax = plt.subplot()
ax.set_xlabel('timestamp (1 sample = 10 minutes)')
ax.set_ylabel('voltage value (p.u.)')
ax.plot([curves.index[0], curves.index[-1]], [1.05, 1.05], '--r')
ax.plot(curves.index, voltage_values['without_pv'], label='without pv')
ax.plot(curves.index, voltage_values['with_pv'], label='with pv')
ax.legend()
figure.savefig('results.pdf')
plt.show()
