import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import argparse
import os
parser = argparse.ArgumentParser(
    description='Realtime Time multi-agent simulation of CIGRE LV network')
parser.add_argument('--pi', action='store_true',
                    help='plot PI results')
parser.add_argument('--opf', action='store_true',
                    help='plot OPF results')
parser.add_argument('--output', type=str,
                    help='output file',
                    default='sim_bars.png')
parser.add_argument('--high-limit', type=float,
                    help='Total simulation time',
                    default=1.05)
parser.add_argument('--low-limit', type=float,
                    help='Total simulation time',
                    default=0.95)
parser.add_argument('--cycles', type=str,
                    help='',
                    default='1,2,3,4,5,6,7,8,9,10')    
parser.add_argument('--results', type=str,
                    help='',
                    default='./experiments/3')
parser.add_argument('--runs', type=int,
                    help='',
                    default=5)                                      
parser.add_argument('--god', action='store_true')
args = parser.parse_args()

with_pi= args.pi
with_opf= args.opf
output = args.output
low = args.low_limit
high = args.high_limit
cycles = [int(i) for i in args.cycles.split(',')]
results = args.results
runs = args.runs
god = args.god

fig = plt.figure()
ax = fig.add_subplot(111)
width=0.4
pv_hits: list = []
for i in range(runs):
    data = pd.read_csv('experiments/3/sim_pv_{}.log'.format(i), header=None, delimiter='\t')
    data[0] = data[0]-data.loc[0,0]
    # data.drop_duplicates(4, inplace=True)
    voltages = data[4]
    pv_hits = pv_hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())]

pv_hits = np.array(pv_hits)
pv_std = np.std(pv_hits)
pv_mean = np.mean(pv_hits)

#data = pd.read_csv('../victor_scripts/cigre/cigre_network_lv.log', header=None)
#hits = data[data[0]>=1.05][0].count()+data[data[0]<=0.95][0].count()

# hits: list = []
for i in cycles: ## Cycle
    pv_bar = ax.bar([i-width], [pv_mean],
            width=width,
            yerr=[pv_std],
            facecolor='red',
            align='center',
            alpha=0.5,
            ecolor='black',
            capsize=2)
#    pv_plot = ax.plot([cycles[0], cycles[-1]], [hits, hits], 'r--')
    pi_hits: list = []
    opf_hits: list = []

    for j in range(runs): ## Run
        if with_opf:
            data = pd.read_csv(os.path.join(results,'sim_opf_{}.{}.'.format(i, j+1)+('b' if god else 'a')+'.log'), header=None, delimiter='\t')
            data[0] = data[0]-data.loc[0,0]
            # data.drop_duplicates(4, inplace=True)
            voltages = data[4]
            opf_hits = opf_hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())]
        if with_pi:
            data = pd.read_csv(os.path.join(results,'sim_pi_{}.{}.'.format(i, j+1)+('b' if god else 'a')+'.log'), header=None, delimiter='\t')
            data[0] = data[0]-data.loc[0,0]
            # data.drop_duplicates(4, inplace=True)
            voltages = data[4]
            pi_hits = pi_hits + [(voltages[(voltages <= low)].count() + voltages[(voltages >= high)].count())]
        if not with_opf and not with_pi:
            break
    
    if with_opf:
        opf_hits = np.array(opf_hits)
        opf_std = np.std(opf_hits)
        opf_mean = np.mean(opf_hits)
        print("mean: {}, std: {}, max: {}, min: {}".format(opf_mean, opf_std, np.max(opf_hits), np.min(opf_hits)))
        opf_bar = ax.bar([i], [opf_mean],
            width=width,
            yerr=[opf_std],
            facecolor='blue',
            align='center',
            alpha=0.5,
            ecolor='black',
            capsize=2)

    if with_pi:
        pi_hits = np.array(pi_hits)
        pi_std = np.std(pi_hits)
        pi_mean = np.mean(pi_hits)
        pi_bar = ax.bar([i+width], [pi_mean],
                    width=width,
                    yerr=[pi_std],
                    facecolor='yellow',
                    align='center',
                    alpha=0.5,
                    ecolor='black',
                    capsize=2)

ax.set_ylabel('Count of voltage values beyond thresholds')
ax.set_xlabel('Control duty-cycle (s)')
ax.set_xticks(cycles)
ax.set_xticklabels(["%ds"%(i) for i in cycles])
# ax.set_yticks([i for i in np.arange(0, 0.09, 0.02)])
# ax.set_yticklabels(["{}%".format(i*100) for i in np.arange(0, 0.09, 0.02)])
# ax.legend((pv_bar[0], opf_bar[0], pi_bar[0]), ('No Control', 'OPF Control', 'PI Control'))
#ax.legend((([opf_bar[0] if with_opf else []], [pi_bar[0] if with_pi else [])), tuple(['OPF Control' if with_opf else []]+ ['PI Control' if with_pi else []]))

plt.savefig(output, dpi=300)
