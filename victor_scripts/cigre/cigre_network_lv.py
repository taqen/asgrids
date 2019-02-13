#!/usr/bin/python3
# -*- coding: utf-8 -*-

import pandapower as pp
import pandas as pd
from matplotlib import pyplot as plt

# load CIGRÉ low voltage distribution network
net = pp.from_json('cigre_network_lv.json')

# load profiles
curves = pd.read_csv('curves.csv')

# load flow
voltages_with_pv = list()
voltages_without_pv = list()
for index, row in curves.iterrows():
    # with PV
    for index_2, row_2 in net.load.iterrows():
        net.load.loc[index_2, 'p_kw'] = row[row_2['name'] + '_P']
        net.load.loc[index_2, 'q_kvar'] = row[row_2['name'] + '_Q']
    pp.runpp(net)
    voltages_with_pv.append(net.res_bus.loc[:, 'vm_pu'])

    # without PV
    for index_2, row_2 in net.load.iterrows():
        if 'PV' in row_2['name']:
            net.load.loc[index_2, 'p_kw'] = 0
            net.load.loc[index_2, 'q_kvar'] = 0
    pp.runpp(net)
    voltages_without_pv.append(net.res_bus.loc[:, 'vm_pu'])

    # log
    print('Timestamp {:.0f} / {:.0f}: without pv = {:.3f} pu, with pv = {:.3f} pu'
          .format(row['timestamp'], len(curves), max(voltages_without_pv[-1]), max(voltages_with_pv[-1])))

# display results
figure = plt.figure()
ax1 = plt.subplot(2, 1, 1)
ax1.boxplot(voltages_without_pv)
ax1.plot([curves.index[0], curves.index[-1]], [1.05, 1.05], '--r')
ax1.set_xticks([])
ax1.set_ylabel('voltage value (p.u.)')
plt.title('Without PV')

ax2 = plt.subplot(2, 1, 2)
ax2.boxplot(voltages_with_pv)
ax2.plot([curves.index[0], curves.index[-1]], [1.05, 1.05], '--r')
ax2.set_xticks([])
ax2.set_xlabel('timestamp (1 sample = 10 minutes)')
ax2.set_ylabel('voltage value (p.u.)')
plt.title('With PV')

plt.show()
figure.savefig('boxplots.pdf')
