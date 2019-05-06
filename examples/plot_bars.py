import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

low = 0.96
high = 1.04

fig = plt.figure()
ax = fig.add_subplot(111)
width=0.2
hits: list = []
for i in range(7):
    data = pd.read_csv('experiments/3/sim_pv_{}.log'.format(i+1), header=None, delimiter='\t')
    data[0] = data[0]-data.loc[0,0]
    voltages = data[4]
    hits = hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())/voltages.count()]
hits = np.array(hits)
pv_std = np.std(hits)
pv_mean = np.mean(hits)

# hits: list = []
for i in range(10): ## Cycle
    pv_bar = ax.bar([i+1-width], [pv_mean],
                width=width,
                yerr=[pv_std],
                facecolor='red',
                align='center',
                alpha=0.5,
                ecolor='black',
                capsize=2)

    pi_hits: list = []
    opf_hits: list = []

    for j in range(10): ## Run
        data = pd.read_csv('experiments/3/sim_opf_{}.{}.log'.format(i+1, j+1), header=None, delimiter='\t')
        data[0] = data[0]-data.loc[0,0]
        voltages = data[4]
        opf_hits = opf_hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())/voltages.count()]
        # print("OPF %d: "%i, hits)
        data = pd.read_csv('experiments/3/sim_pi_{}.{}.log'.format(i+1, j+1), header=None, delimiter='\t')
        data[0] = data[0]-data.loc[0,0]
        voltages = data[4]
        pi_hits = pi_hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())/voltages.count()]
        # print("PI %d: "%i, hits)
    
    opf_hits = np.array(opf_hits)
    opf_std = np.std(opf_hits)
    opf_mean = np.mean(opf_hits)
    pi_hits = np.array(pi_hits)
    pi_std = np.std(pi_hits)
    pi_mean = np.mean(pi_hits)

    opf_bar = ax.bar([i+1], [opf_mean],
                width=width,
                yerr=[opf_std],
                facecolor='blue',
                align='center',
                alpha=0.5,
                ecolor='black',
                capsize=2)
    pi_bar = ax.bar([i+1+width], [pi_mean],
                width=width,
                yerr=[pi_std],
                facecolor='yellow',
                align='center',
                alpha=0.5,
                ecolor='black',
                capsize=2)
    # plt.show()
ax.set_ylabel('%% of voltage values beyond thresholds')
ax.set_xlabel('Control duty-cycle (s)')
ax.set_xticks([i+1 for i in range(10)])
ax.set_xticklabels(["%ds"%(i+1) for i in range(10)])
ax.set_yticks([i for i in np.arange(0, 0.09, 0.02)])
ax.set_yticklabels(["{}%".format(i*100) for i in np.arange(0, 0.09, 0.02)])
ax.legend((pv_bar[0], opf_bar[0], pi_bar[0]), ('No Control', 'OPF Control', 'PI Control'))
plt.savefig('sim_bars.png', dpi=300)