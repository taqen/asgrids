import matplotlib.pyplot as plt
import pandas as pd
import pandapower.networks as pn

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

nNodes = []
mem = []
for case in cases.keys():
    data = pd.read_csv('experiments/profiling/2/mprof_{}.dat'.format(case), header=None, skiprows=1, delimiter=' ')
    net = cases[case]()
    nNodes.append(len(net.load.index))
    mem.append(max(data[1].tolist()))
fig = plt.figure()
ax = fig.add_subplot(111)
p1 = ax.plot(nNodes, mem, color="blue")

nNodes = []
mem = []
for case in cases.keys():
    data = pd.read_csv('experiments/profiling/1/mprof_{}.dat'.format(case), header=None, skiprows=1, delimiter=' ')
    net = cases[case]()
    nNodes.append(len(net.load.index))
    mem.append(max(data[1].tolist()))
p2 = ax.plot(nNodes, mem, color="yellow")

ax.set_ylabel("Maximum memory allocated for the simulation (MiB)")
ax.set_xlabel("Number of simulated nodes")
ax.legend((p1[0], p2[0]), ('Low traffic', 'High traffic'))
plt.savefig("memory_consumption.png", dpi=600)