#%%import matplotlib.pyplot as plt
import pandas as pd
import pandapower.networks as pn
import matplotlib.pyplot as plt
from numpy import mean, std, max, min, arange

cases = {"case6ww": pn.case6ww,
         "case9": pn.case9,
         "case14": pn.case14,
         "case30": pn.case30,
         "case_ieee30": pn.case_ieee30,
         "case33bw": pn.case33bw,
         "case39": pn.case39,
         "case57": pn.case57,
         "case118": pn.case118,
         "case300": pn.case300
         }

#%%
nodes = [10, 20, 50, 100, 300, 500]
mem: list = []
cpu: list = []
for i in nodes:
    data = pd.read_csv('./profiling/ps.{}.2.out'.format(i), skiprows=1, header=None, delimiter=r"\s+")
    mem.append([m for m in data[2][3:300] if m>=0])
    cpu.append([m for m in data[1][3:300] if m>=0])
#%%
fig = plt.figure()
ax_mem = fig.add_subplot(111)
# plot_mem = ax_mem.errorbar(nodes, [mean(m) for m in mem], yerr=[std(m) for m in mem], color='blue')
plot_mem = ax_mem.plot(nodes, [mean(m) for m in mem], 'd-', color="blue")
ax_mem.set_ylabel("Average Memory Consumption (MiB)", color="blue", fontsize=12)
ax_mem.set_ylim(140, 240)
ax_mem.xaxis.set_tick_params(labelsize=12)
ax_mem.yaxis.set_tick_params(labelsize=12)

print([mean(c) for c in cpu])
ax_cpu = ax_mem.twinx()
# plot_mem = ax_mem.errorbar(nodes, [mean(m) for m in cpu], yerr=[std(m) for m in cpu], color='red')
plot_mem = ax_cpu.plot(nodes, [mean(m) for m in cpu], 'd-', color="red")
ax_cpu.set_yticks([i for i in arange(int(min([min(m) for m in cpu])),int(max([max(m) for m in cpu])), 30)])
ax_cpu.set_ylabel('Average CPU usage (%)', color="red", fontsize=12)
ax_cpu.set_ylim(0, 120)
ax_cpu.xaxis.set_tick_params(labelsize=12)
ax_cpu.yaxis.set_tick_params(labelsize=12)

plt.show()