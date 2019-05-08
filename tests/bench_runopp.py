#!/usr/bin/env python
# -*- coding: utf-8 -*-

import random
import timeit

import matplotlib.pyplot as plt
import numpy as np
import pandapower as pp
import pandapower.networks as pn
from joblib import Parallel, delayed

# %%
cases ={
    "case6ww":pn.case6ww,
    "case9":pn.case9,
    "case14":pn.case14,
    "case30":pn.case30,
    "case_ieee30":pn.case_ieee30,
    "case33bw":pn.case33bw,
    "case39":pn.case39,
    "case57":pn.case57,
    "case118":pn.case118,
    "case300":pn.case300,
}


# %%
def run(func, net, repeat=1):
    # net = eval("pn.{}()".format(case), globals(), locals())

    def update_net():
        func(net, init_vm_pu='results')
        for row in net.load.iterrows():
            net.load['p_kw'][row[0]] = row[1]['p_kw'] * (1 + random.uniform(0, 1e-3))
            net.load['q_kvar'][row[0]] = row[1]['q_kvar'] * (1 + random.uniform(0, 1e-3))

    t = timeit.Timer("update_net()", globals=locals(), setup="import pandapower as pp")
    try:
        bench = t.repeat(repeat=repeat, number=1)
        print([len(net.load.index), bench])
        return [len(net.load.index), bench]
    except pp.optimal_powerflow.OPFNotConverged:
        print("optimal flow calculation for {} didn't converge")
    except UserWarning as e:
        print(e)


# %%capture
results = Parallel(n_jobs=8)(
    delayed(run)(pp.runpp, cases[case](), 10) for case in cases.keys())

# %%
fig, ax = plt.subplots(figsize=(10, 5))
index = np.arange(len(cases))
means = [np.mean(result[1]) for result in results]
stds = [np.std(result[1]) for result in results]
rects1 = ax.bar(index, means, width=0.35,
                alpha=0.4, color='b', align='center',
                yerr=stds, error_kw={'ecolor': '0.3'})
ax.set_xlabel('IEEE test case')
ax.set_ylabel('power flow analysis runtime')
ax.set_xticks(index)
ax.set_xticklabels((result[0] for result in results))
fig.tight_layout()
plt.savefig('pp_time.png', dpi=600)

# %%capture
results = Parallel(n_jobs=8)(
    delayed(run)(pp.runopp, cases[case](), 10) for case in cases.keys())

# %%
fig, ax = plt.subplots(figsize=(10, 5))
index = np.arange(len(cases))
means = [np.mean(result[1]) for result in results]
stds = [np.std(result[1]) for result in results]
rects1 = ax.bar(index, means, width=0.35,
                alpha=0.4, color='b', align='center',
                yerr=stds, error_kw={'ecolor': '0.3'})
ax.set_xlabel('IEEE test case')
ax.set_ylabel('optimal power flow runtime')
ax.set_xticks(index)
ax.set_xticklabels((result[0] for result in results))
fig.tight_layout()
plt.savefig('opff_time.png', dpi=600)
