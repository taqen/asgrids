import pandas as pd
import matplotlib.pyplot as plt
from numpy import max, std, ceil, arange, sort, Inf
import numpy as np
from statsmodels.distributions.empirical_distribution import ECDF
import argparse
import os
from pandas.api.types import is_string_dtype
from itertools import cycle
import pickle
from scipy.integrate import trapz

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

data_tcp: dict = {}
data_udp: dict = {}
data_nc = 35970.01922997645 #original data

def filter_data(data):
    if is_string_dtype(data[0]):
        data = data.drop(data[data[0].str.contains('VOLTAGE')].index)
        data[0]=data[0].str.replace('LOAD ', '')
        data[0]=pd.to_numeric(data[0],errors='coerce')
        data = data.reset_index(drop=True)
    data[0]=data[0]-data.loc[0,0]
    data = data.drop(data[data[0]>200].index)
    return data

def get_power_loss(data):
    data = filter_data(data)
    total = 0
    data = data.groupby(1)
    for name, g in data:
        value = sum(g[2])
        if value <=0:
            total = total + sum(g[2])
    data = 1-abs(total)/data_nc
    return data

if load != '':
    with open(load, 'rb') as pickle_file:
        data_tcp, data_udp = pickle.load(pickle_file)

else:
    for j in losses:
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

        data_tcp[j] = []
        data_udp[j] = []
        for i in runs:
            try:
                data = pd.read_csv(os.path.join(results, 'tcp', 'sim.opf.{}loss.{}.log'.format(loss,i)), header=None, delimiter='\t')
                data_tcp[j] = data_tcp[j] + [100*get_power_loss(data)]
            except Exception as e:
                print(e)
            try:    
                data = pd.read_csv(os.path.join(results, 'udp', 'sim.pi.{}loss.{}.log'.format(loss,i)), header=None, delimiter='\t')
                data_udp[j] = data_tcp[j] + [100*get_power_loss(data)]
            except Exception as e:
                print(e)
if save != '':
    with open(save, 'wb') as pickle_file:
        pickle.dump([data_tcp, data_udp], pickle_file)


fig = plt.figure(figsize=figsize)
ax = fig.add_subplot(111)
for j in losses:
    x = [0, 2, 4, 6, 8]

    #plotting for tcp
    values = list(data_tcp.values())
    y = [np.mean(i) for i in values]
    stdy = [np.std(i) for i in values]
    tcp_bar = ax.bar([i-width/2 for i in x], y, yerr=stdy, color='blue', width=width, label="%d%% loss"%j)

    #plotting for udp
    values = list(data_udp.values())
    y = [np.mean(i) for i in values]
    stdy = [np.std(i) for i in values]
    udp_bar = ax.bar([i+width/2 for i in x], y, yerr=stdy, color='green', width=width, label="%d%% loss"%j)

    # ax.set_xticks([0, 10, 20, 30, 60])
    ax.set_xticklabels(["0%", "10%", "20%", "30%", "60%"], fontsize=12)
    ax.set_ylabel("Production lost (%)", fontsize=14)
    ax.set_xlabel("Packet loss (%)", fontsize=14)
    ax.xaxis.set_tick_params(labelsize=12)
    ax.yaxis.set_tick_params(labelsize=12)

    legend_items = [tcp_bar[0], udp_bar[0]]
    legend_labels = ["OPF+TCP", "OPF+UDP"]
    ax.legend(legend_items, legend_labels, loc="upper right", prop={'size': 14})

plt.tight_layout()
plt.savefig(output, figsize=figsize, dpi=600)
plt.show()