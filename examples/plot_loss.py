#%%
import pandas as pd
import matplotlib.pyplot as plt
from numpy import std, ceil, arange, sort, Inf, mean
import argparse
import os
from pandas.api.types import is_string_dtype
import pickle
#%%
losses = [0, 10, 20, 30, 60]
runs = [1, 2, 3, 4, 5]
with_pi = True
with_opf = True
max_vm = 1.05
results = './examples/asgrids'
plot_type = 'barplot'
output = './examples/bars_loss.png'
tslice = [0, Inf]
width = 1

#%%
parser = argparse.ArgumentParser(
    description='Plotting ECDF')
parser.add_argument('--slice', type=str,
                    help='plot from a time slice of the whold data. [t1, t2]',
                    default='all')
parser.add_argument('--type', required=False, type=str, 
                    choices=['barplot', 'boxplot'],
                    default='boxplot')
parser.add_argument('--output', required=False, type=str, 
                    default='boxplot_loss.png')
parser.add_argument('--results', type=str, 
                    default='./raw')
parser.add_argument('--with-pi', action="store_true",
                    help='plot PI data as well')
parser.add_argument('--with-opf', action="store_true",
                    help='plot OPF data as well')
parser.add_argument('--runs', nargs='+', type=int,
                    default=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
parser.add_argument('--losses', nargs='+', type=int,
                    default=[0, 5, 10, 15, 20, 40, 50, 60])
parser.add_argument('--max-vm', type=float,
                    default=1.05)
parser.add_argument('--width', type=float,
                    default=1)
parser.add_argument('--save', type=str, default='')
parser.add_argument('--load', type=str, default='')

#%%
args = parser.parse_args()
save = args.save
load = args.load
losses = args.losses
runs = args.runs
with_pi = args.with_pi
with_opf = args.with_opf
max_vm = args.max_vm
if not (with_pi or with_opf):
    print("Nothing to plot. You might wanna select PI and/or OPF flags.")
    exit()
results = args.results
plot_type = args.type
output = args.output
tslice = args.slice
if tslice != 'all':
    tslice = [float(i) for i in args.slice.split(',')]
    if len(tslice) == 1:
        tslice.append(Inf)
else:
    tslice = [0, Inf]

assert len(tslice) == 2
width=args.width

#%%
def calculate_rate(data, slice_range: list = [0, Inf]):
        if is_string_dtype(data[0]):
            data.drop(data[data[0].str.contains('LOAD')].index, inplace=True)
            data[0]=data[0].str.replace('VOLTAGE ', '')
            data[0]=pd.to_numeric(data[0],errors='coerce')
            data.reset_index(drop=True, inplace=True)
        data[0]=data[0]-data.loc[0,0]
        # sample every 1s
        # data[0]=data[0].apply(ceil)
        # data.drop_duplicates(subset=[0,1], inplace=True, keep='last')
        
        data.drop(data[data[0]>287].index, inplace=True)
        data.drop(data[data[0]==0].index, inplace=True)
        data.reset_index(drop=True, inplace=True)
        if slice_range != [0, Inf]:
            data.drop(data[data[0]<tslice[0]].index, inplace=True)
            data.reset_index(drop=True, inplace=True)
            data.drop(data[data[0]>tslice[1]].index, inplace=True)
            data.reset_index(drop=True, inplace=True)
        return data[data[2]>=max_vm][2].count()/data[2].count()

#%%
hits_opf: dict = {}
hits_pi: dict = {}

data = pd.read_csv(os.path.join(results, 'sim_no_control.log'), header=None, delimiter='\t')
hits_pv =  [calculate_rate(data)]
#%%
for j in losses:
    hits_opf[j] = []
    hits_pi[j] = []

    for i in runs:
        if with_opf:
            try:
                data = pd.read_csv(os.path.join(results, 'sim_opf_{}loss.{}.log'.format(j,i)), header=None, delimiter='\t')
                hits_opf[j] = hits_opf[j] + [calculate_rate(data)]
            except Exception as e:
                print("ERROR:", e)
        if with_pi:
            try:
                data = pd.read_csv(os.path.join(results, 'sim_pi_{}loss.{}.log'.format(j,i)), header=None, delimiter='\t')
                hits_pi[j] = hits_pi[j] + [calculate_rate(data)]
            except Exception as e:
                print(e)

#%%
fig = plt.figure()
print("Generating %s"%plot_type)
if plot_type is 'boxplot':
    ax_opf = None
    ax_pi = None
    if not (with_pi or with_opf):
        exit()
    ax = fig.add_subplot(111)
    # elif with_pi and with_opf:
    #     ax_opf = fig.add_subplot(121)
    #     ax_pi = fig.add_subplot(122)
    # elif with_opf:
    #     ax_opf = fig.add_subplot(111)
    # else:
    #     ax_pi = fig.add_subplot(111)
    pv_plot = ax.plot([0, 20], [hits_pv, hits_pv], color='red')
    if with_opf:
        box = []
        # ax = ax_opf
        for v in hits_opf.values():
            box.append(v)
        opf_box=ax.boxplot(box, showfliers=False, notch=True, patch_artist=True, boxprops=dict(facecolor="green"))
        pv_plot = ax.plot([0, 20], [hits_pv, hits_pv], color='red')
        ax.scatter(ax.get_xticks(), [mean(i) for i in hits_opf.values()])
        ax.set_xlabel('packet loss rate(%)')
        ax.set_ylabel('Voltage violation rate')
        ax.set_xticklabels(["{}%".format(j) for j in losses])
        ax.set_yticks([i for i in arange(0, max(hits_pv)+0.02, 0.1)])
        ax.set_yticklabels(["%0.1f%%"%(j*100) for j in arange(0, max(hits_pv)+0.02, 0.1)])
    if with_pi:
        # ax = ax_pi
        box = []
        for v in hits_pi.values():
            box.append(v)
        pi_box=ax.boxplot(box, showfliers=False, notch=True, patch_artist=True, boxprops=dict(facecolor="blue"))
        ax.scatter(ax.get_xticks(), [mean(i) for i in hits_pi.values()])
        ax.set_xlabel('packet loss rate(%)')
        ax.set_ylabel('Voltage violation rate')
        ax.set_xticks([losses])
        ax.set_xticklabels(["{}%".format(j) for j in losses])
        ax.set_yticks([i for i in arange(0, max(hits_pv)+0.02, 0.1)])
        ax.set_yticklabels(["%0.1f%%"%(j*100) for j in arange(0, max(hits_pv)+0.02, 0.1)])

    ax.legend([pv_plot[0], pi_box["boxes"][0], opf_box["boxes"][0]], ['No Control', 'PI Control', 'OPF Control'], loc='upper right')

else:
    ax = fig.add_subplot(111)
    x = [0, 5, 10, 15, 20]
    pv_plot = ax.plot(x, [hits_pv for i in x], color='red')
    if with_opf:
        opf_bar = ax.bar([i-width/2 for i in x], [mean(i) for i in hits_opf.values()], yerr=[std(i) for i in hits_opf.values()], color='blue', width=width)
    if with_pi:
        pi_bar = ax.bar([i+width/2 for i in x], [mean(i) for i in hits_pi.values()], yerr=[std(i) for i in hits_pi.values()], color='green', width=width)


    legend_items = [pv_plot[0]]
    if with_opf:
        legend_items = [opf_bar[0]] + legend_items
    if with_pi:
        legend_items = [pi_bar[0]] + legend_items
    legend_labels = ["No Control(NC)"]
    if with_opf:
        legend_labels = ["OPF Control"] + legend_labels
    if with_pi:
        legend_labels = ["PI Control"] + legend_labels
    ax.set_xticks(x)
    ax.set_xticklabels(losses)
    ax.set_ylim(0.04, 0.08)
    # yticks = [i for i in arange(0, max(hits_pv)+0.02, 0.01)]
    yticks = ax.get_yticks()
    ax.set_yticklabels(["%0.1f%%"%(j*100) for j in yticks])
    ax.legend(legend_items, legend_labels, loc="lower left")
    ax.set_ylabel("Voltage violations (%)")
    ax.set_xlabel("Packet loss (%)")
    ax.set_ylim(0.04, 0.08)
#%%
plt.tight_layout()
plt.savefig(output, dpi=600)
plt.show()