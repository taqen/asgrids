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
parser.add_argument('--slice', type=str,
                    help='plot from a time slice of the whold data. [t1, t2]',
                    default='all')
parser.add_argument('--with-opf', action="store_true",
                    help='plot OPF data as well')
parser.add_argument('--with-pi', action="store_true",
                    help='plot PI data as well')
parser.add_argument('--results', type=str, 
                    default='./raw')
parser.add_argument('--runs', nargs='+', type=int,
                    default=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
parser.add_argument('--losses', nargs='+', type=int,
                    default=[0, 5, 10, 15, 20, 40, 50, 60])
parser.add_argument('--max-vm', type=float,
                    default=1.05)
parser.add_argument('--save', type=str, default='')
parser.add_argument('--load', type=str, default='')
parser.add_argument('--output', type=str, default='./ecdf_power_loss.png')

args = parser.parse_args()
output = args.output
save = args.save
load = args.load
losses = args.losses
max_vm = args.max_vm
runs = args.runs
results = args.results
tslice = args.slice
with_pi = args.with_pi
with_opf = args.with_opf

if tslice != 'all':
    tslice = [float(i) for i in args.slice.split(',')]
    if len(tslice) == 1:
        tslice.append(Inf)
else:
    tslice = [0, Inf]

assert len(tslice) == 2

width=0.4
data_opf: dict = {}
data_pi: dict = {}
data_pv = 35970.01922997645 #original data

def filter_data_power(data):
    if is_string_dtype(data[0]):
        data = data.drop(data[data[0].str.contains('VOLTAGE')].index)
        data[0]=data[0].str.replace('LOAD ', '')
        data[0]=pd.to_numeric(data[0],errors='coerce')
        data = data.reset_index(drop=True)
    data[0]=data[0]-data.loc[0,0]
    return data

def get_voltages(data, slice: list = [0, Inf]):
    assert len(slice) <=2
    data = filter_data_power(data)
    data.drop(data[data[0]>287].index, inplace=True)
    data.drop(data[data[0]==0].index, inplace=True)
    data.reset_index(drop=True, inplace=True)
    # slicing
    total = 0
    data = data.groupby(1)
    for name, g in data:
        value = sum(g[2])
        if value <=0:
            print("{}: {}".format(name, sum(g[2])))
            total = total + sum(g[2])
    # print(data)
    return 1-abs(total)/data_pv

if load != '':
    with open(load, 'rb') as pickle_file:
        data_opf, data_pi = pickle.load(pickle_file)

else:
    for j in losses:
        data_opf[j] = []
        data_pi[j] = []
        for i in runs:
            try:
                if with_opf:
                    print("reading for opf {}% loss: {}".format(j, i))
                    data = pd.read_csv(os.path.join(results, 'sim.opf.{}loss.{}.log'.format(j,i)), header=None, delimiter='\t')
                    data_opf[j] = data_opf[j] + get_voltages(data)
                if with_pi:
                    print("reading for pi {}% loss: {}".format(j, i))
                    data = pd.read_csv(os.path.join(results, 'sim.pi.{}loss.{}.log'.format(j,i)), header=None, delimiter='\t')
                    data_pi[j] = data_opf[j] + get_voltages(data)
            except Exception as e:
                print(e)
if save != '':
    with open(save, 'wb') as pickle_file:
        pickle.dump([data_opf, data_pi], pickle_file)


fig = plt.figure()
# ax1 = fig.add_subplot(121)
# ax2 = fig.add_subplot(122)
ax = fig.add_subplot(111)
lines = ["-"]
colors = ["blue", "blue", "green", "green"]
linecycler = cycle(lines)
colorcycler = cycle(colors)
size=10
i=1
# ax.plot([0, 40], [1, 0], color='red')
for j in losses:
    if with_opf:
        # ecdf_opf = ECDF(data_opf[j])
        # x = data_opf[j]
        # x.sort()
        # y = ecdf_opf(x)
        x = [i-0.5]
        y = [abs(np.mean(data_opf[j]))]
        stdy = [abs(np.std(data_pi[j]))]
        print(x, y)
        ax.bar(x, y, yerr=stdy, color='blue', width=1, label="%d%% loss"%j)
    if with_pi:
        # ecdf_pi = ECDF(data_pi[j])
        # x = data_pi[j]
        # x.sort()
        # y = ecdf_pi(x)
        x = [i+0.5]
        y = [abs(np.mean(data_pi[j]))]
        stdy = [abs(np.std(data_pi[j]))]
        print(x, y)
        ax.bar(x, y, yerr=stdy, color='green', width=1, label="%d%% loss"%j)
    ax.set_xticks([0, 10, 20, 30, 40])
    ax.set_xticklabels(["0%", "10%", "20%", "30%", "60%"])
    i=i+10

plt.tight_layout()
plt.savefig(output, figsize=(500,1000), dpi=600)
plt.show()