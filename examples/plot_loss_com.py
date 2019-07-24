#%%
import pandas as pd
import matplotlib.pyplot as plt
from numpy import std, ceil, arange, sort, Inf, mean
import argparse
import os
from pandas.api.types import is_string_dtype
import pickle

#%%
def filter_data(data):
    if is_string_dtype(data[0]):
        data.drop(data[data[0].str.contains('LOAD')].index, inplace=True)
        data[0]=data[0].str.replace('VOLTAGE ', '')
        data[0]=pd.to_numeric(data[0],errors='coerce')
        data.reset_index(drop=True, inplace=True)
    data[0]=data[0]-data.loc[0,0]
    return data

#%%
def calculate_rate(data):
    data = filter_data(data)
    data = data.reset_index(drop=True)
    data = data[data[2]>=max_vm][2].count()/data[2].count()
    return data

#%%
parser = argparse.ArgumentParser(
    description='Plotting ECDF')
parser.add_argument('--type', required=False, type=str, 
                    choices=['barplot', 'boxplot'],
                    default='barplot')
parser.add_argument('--output', required=False, type=str, 
                    default='bars_loss.png')
parser.add_argument('--results', type=str, 
                    default='./results')
parser.add_argument('--runs', nargs='+', type=int,
                    default=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
parser.add_argument('--losses', nargs='+', type=int,
                    default=[0, 10, 20, 30, 60])
parser.add_argument('--max-vm', type=float,
                    default=1.05)
parser.add_argument('--width', type=float,
                    default=1)
parser.add_argument('--save', type=str, default='')
parser.add_argument('--load', type=str, default='')
parser.add_argument('--figsize', nargs=2, type=int, default=[9, 3])

#%%
args = parser.parse_args()
save = args.save
load = args.load
losses = args.losses
runs = args.runs
max_vm = args.max_vm
figsize = args.figsize
results = args.results
plot_type = args.type
output = args.output
width=args.width

#%%

#%%
hits_tcp: dict = {}
hits_udp: dict = {}
hits_nc: list = []
if load != '':
    with open(load, 'rb') as pickle_file:
        hits_tcp, hits_udp, hits_nc = pickle.load(pickle_file)
else:
    try:
        data = pd.read_csv(os.path.join(results, 'sim_no_control.log'), header=None, delimiter='\t')
        hits_nc =  [calculate_rate(data)]
    except Exception as e:
        hits_nc = [10]

    for j in losses:
        hits_tcp[j] = []
        hits_udp[j] = []
        loss = ''
        if j == 0:
            loss = '127.0.0.1'
        elif j == 10:
            loss = '127.0.2.1'
        elif j == 20:
            loss = '127.0.3.1'
        elif j == 30:
            loss = '127.0.4.1'
        elif j == 60:
            loss = '127.0.5.1'
        else:
            raise ValueError(loss)


        for i in runs:
            try:
                print('reading {}'.format(os.path.join(results, 'tcp', 'sim.opf.{}loss.{}.log'.format(loss,i))))
                data = pd.read_csv(os.path.join(results, 'tcp', 'sim.opf.{}loss.{}.log'.format(loss,i)), header=None, delimiter='\t')
                hits_tcp[j] = hits_tcp[j] + [100*calculate_rate(data)]
            except Exception as e:
                print("TCP READ ERROR:", e)
            try:
                print('reading {}'.format(os.path.join(results, 'udp', 'sim.opf.{}loss.{}.log'.format(loss,i))))
                data = pd.read_csv(os.path.join(results, 'udp', 'sim.opf.{}loss.{}.log'.format(loss,i)), header=None, delimiter='\t')
                hits_udp[j] = hits_udp[j] + [100*calculate_rate(data)]
            except Exception as e:
                print("UDP READ ERROR:", e)

if save != '':
    try:
        with open(save, 'wb') as pickle_file:
            pickle.dump([hits_tcp, hits_udp, hits_nc], pickle_file)
    except Exception as e:
        print("Erroring pickling to file {}: {}".format(save, e))

print([mean(hits_tcp[i]) for i in hits_tcp])
print([mean(hits_udp[i]) for i in hits_udp])

#%%
fig = plt.figure(figsize=figsize)
print("Generating %s"%plot_type)
if plot_type == 'boxplot':
    ax_opf = None
    ax = fig.add_subplot(111)
    nc_plot = ax.plot(losses, [hits_nc for i in losses], color='red', label="No Control")
    box = []
    # ax = ax_opf
    for v in hits_tcp.values():
        box.append(v)
    tcp_box=ax.boxplot(box, showfliers=False, notch=False, patch_artist=True, boxprops=dict(facecolor="blue"))
    tcp_box["boxes"][0].set_label("OPF Control")
    ax.scatter(ax.get_xticks(), [mean(i) for i in hits_tcp.values()])
    ax.set_xlabel('packet loss rate(%)')
    ax.set_ylabel('Voltage violation rate')
    ax.set_xticklabels(["{}%".format(j) for j in losses])
    # ax.set_yticks([i for i in arange(0, max(hits_nc)+0.02, 0.1)])
    # ax.set_yticklabels(["%0.1f%%"%(j*100) for j in arange(0, max(hits_nc)+0.02, 0.1)])
    ax.legend(loc='upper right')

else:
    ax = fig.add_subplot(111)
    # Plotting baseline, no control
    x = [0, 2, 4, 6, 8]
    nc_plot = ax.plot(x, [hits_nc for i in x], color='red')
    
    # Plotting tcp data
    values = list(hits_tcp.values())
    y = [mean(i) for i in values]
    stdy = [std(i) for i in values]
    tcp_bar = ax.bar([i-width/2 for i in x], y, yerr=stdy, color='blue', width=width)

    # Plotting udp data
    values = list(hits_udp.values())
    y = [mean(i) for i in values]
    stdy = [std(i) for i in values]
    udp_bar = ax.bar([i+width/2 for i in x], y, yerr=stdy, color='green', width=width)

    legend_items = [tcp_bar[0], udp_bar[0], nc_plot[0]]
    legend_labels = ["OPF+TCP", "OPF+UDP", "No Control(NC)"]
    ax.set_xticks(x)
    ax.set_xticklabels(losses)
    ax.legend(legend_items, legend_labels, loc="upper right", prop={'size': 14})
    ax.set_ylabel("Voltage violations (%)", fontsize=14)
    ax.set_xlabel("Packet loss (%)", fontsize=14)
    ax.xaxis.set_tick_params(labelsize=12)
    ax.yaxis.set_tick_params(labelsize=12)
plt.tight_layout()
plt.savefig(output, figsize=figsize, dpi=600)