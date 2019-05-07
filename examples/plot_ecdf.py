import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from numpy import arange
from statsmodels.distributions.empirical_distribution import ECDF
from mpl_toolkits.axes_grid1.inset_locator import zoomed_inset_axes
from mpl_toolkits.axes_grid1.inset_locator import mark_inset
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

args = parser.parse_args()
results = args.results
runs = args.runs
cycles = [int(i) for i in args.cycles.split(',')]

pv_voltages: list = []
for i in range(runs):
    data = pd.read_csv(os.path.join("./experiments/3", 'sim_pv_%d.log'%(i+1)), header=None, delimiter='\t')
    data[0] = data[0]-data.loc[0,0]
    data.drop_duplicates(4, inplace=True)
    pv_voltages = pv_voltages + data[4].tolist()
pv_ecdf = ECDF(pv_voltages)
pv_voltages = [i for i in arange(0.9, 1.1, 0.001)]
# ecdf: list = []
for i in cycles: ## Cycle
    fig = plt.figure()
    ax = fig.add_subplot(111)

    opf_voltages: list = []
    pi_voltages: list = []
    for j in range(runs): ## Run
        data = pd.read_csv(os.path.join(results, 'sim_opf_{}.{}.b.log'.format(i, j+1)), header=None, delimiter='\t')
        data[0] = data[0]-data.loc[0,0]
        data.drop_duplicates(4, inplace=True)
        opf_voltages = opf_voltages+data[4].tolist()
        # print("OPF %d: "%i, ecdf)
        data = pd.read_csv(os.path.join(results, 'sim_pi_{}.{}.b.log'.format(i, j+1)), header=None, delimiter='\t')
        data[0] = data[0]-data.loc[0,0]
        data.drop_duplicates(4, inplace=True)
        pi_voltages = pi_voltages + data[4].tolist()
        # print("PI %d: "%i, ecdf)
    opf_ecdf = ECDF(opf_voltages)
    pi_ecdf = ECDF(pi_voltages)
    opf_voltages = [i for i in arange(0.9, 1.1, 0.001)]
    pi_voltages = [i for i in arange(0.9, 1.1, 0.001)]

    pv_plot = ax.plot(pv_voltages, pv_ecdf(pv_voltages), '-', color='red')
    ax.plot([1], pv_ecdf(1), marker='v', color='red')
    ax.plot([1, 1], [0, pv_ecdf(1)], '--', color='red', alpha=0.5)
    ax.plot([0, 1], [pv_ecdf(1), pv_ecdf(1)], '--', color='red', alpha=0.5)

    opf_plot = ax.plot(opf_voltages, opf_ecdf(opf_voltages), '-', color='blue')
    ax.plot([1], opf_ecdf(1), marker='^', color='blue')
    ax.plot([1, 1], [0, opf_ecdf(1)], '--', color='blue', alpha=0.5)
    ax.plot([0, 1], [opf_ecdf(1), opf_ecdf(1)], '--', color='blue', alpha=0.5)

    pi_plot = ax.plot(pi_voltages, pi_ecdf(pi_voltages), '-', color='yellow')
    ax.plot([1], pi_ecdf(1), marker='d', color='yellow')
    ax.plot([1, 1], [0, pi_ecdf(1)], '--', color='yellow', alpha=0.5)
    ax.plot([0, 1], [pi_ecdf(1), pi_ecdf(1)], '--', color='yellow', alpha=0.5)
    ax.set_xlim([0.94, 1.06])
    # ax.spines['bottom'].set_position(('data', 0))

    ax.fill_between([0.95, 1.05], [1, 1], color='gray', alpha=0.1)
    yticks = [i for i in np.arange(0, 1, 0.3)]# + [opf_ecdf(1), pv_ecdf(1), pi_ecdf(1)]
    yticks.sort()
    ax.set_yticks(yticks)
    ax.set_ylabel('ECDF Value')
    ax.set_xlabel('vm_pu value')
    ax.legend((pv_plot[0], opf_plot[0], pi_plot[0]), ('No Control', 'OPF Control', 'PI Control'))

    # Insert zoomed portion
    axins = zoomed_inset_axes(ax, 8, loc=4) # zoom = 6
    axins.plot(pv_voltages, pv_ecdf(pv_voltages), '-', color='red')
    axins.plot([1], pv_ecdf(1), marker='v', color='red')
    axins.plot([1, 1], [0, pv_ecdf(1)], '--', color='red', alpha=0.5)
    axins.plot([0, 1], [pv_ecdf(1), pv_ecdf(1)], '--', color='red', alpha=0.5)
    axins.plot(opf_voltages, opf_ecdf(opf_voltages), '-', color='blue')
    axins.plot([1], opf_ecdf(1), marker='^', color='blue')
    axins.plot([1, 1], [0, opf_ecdf(1)], '--', color='blue', alpha=0.5)
    axins.plot([0, 1], [opf_ecdf(1), opf_ecdf(1)], '--', color='blue', alpha=0.5)
    axins.plot(pi_voltages, pi_ecdf(pi_voltages), '-', color='yellow')
    axins.plot([1], pi_ecdf(1), marker='d', color='yellow')
    axins.plot([1, 1], [0, pi_ecdf(1)], '--', color='yellow', alpha=0.5)
    axins.plot([0, 1], [pi_ecdf(1), pi_ecdf(1)], '--', color='yellow', alpha=0.5)

    axins.fill_between([0.998, 1.001], [1, 1], color='gray', alpha=0.2)
    x1, x2, y1, y2 = 0.998, 1.001, pv_ecdf(0.999), (opf_ecdf(1))*1.005
    axins.set_xlim(x1, x2)
    axins.set_ylim(y1, y2)
    axins.set_xticks([])
    yticks = [pv_ecdf(1), opf_ecdf(1), pi_ecdf(1)]
    yticks.sort()
    axins.set_yticks(yticks)
    axins.set_yticklabels(['%0.2f'%i for i in yticks], fontsize=8)
    mark_inset(ax, axins, loc1=1, loc2=2, fc="none", ec="0.5")
    plt.savefig('sim_ecdf_%d'%(i), dpi=300)
    plt.close()
# ax.set_ylabel('Count of voltage values beyond thresholds')
# ax.set_xticks([i+1 for i in range(10)])
# ax.set_xticklabels(["%ds"%(i+1) for i in range(10)])
# plt.show()