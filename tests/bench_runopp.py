#%%
import timeit
from joblib import Parallel, delayed
from multiprocessing import Queue
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
#%%
cases=[
    "case6ww",
    "case9",
    "case14",
    "case30",
    "case_ieee30",
    "case33bw",
    "case39",
    "case57",
    "case118",
    "case300",
]
#%%
def runopp(case, repeat=1):
    import pandapower.networks as pn
    import pandapower as pp
    net = eval("pn.{}()".format(case), globals(), locals())
    t = timeit.Timer("pp.runopp(net)", globals=locals(), setup="import pandapower as pp")
    try:
        bench = t.repeat(repeat=repeat, number=1)
        print([case, bench])
        return [case, bench]
    except pp.optimal_powerflow.OPFNotConverged:
        print("optimal flow calculation for {} didn't converge")
    except UserWarning as e:
        print(e)
        
#%%capture
results = Parallel(n_jobs=8)(
    delayed(runopp)(case, 10) for case in cases)

#%%
fig, ax = plt.subplots(figsize=(10,5))
index = np.arange(len(cases))
means = [np.mean(result[1]) for result in results]
stds = [np.std(result[1]) for result in results]
rects1 = ax.bar(index, means, width=0.35,
            alpha=0.4, color='b', align='center',
            yerr=stds, error_kw={'ecolor': '0.3'})
ax.set_xlabel('IEEE test case')
ax.set_ylabel('runtime')
ax.set_xticks(index)
ax.set_xticklabels((result[0] for result in results))
fig.tight_layout()
plt.show()