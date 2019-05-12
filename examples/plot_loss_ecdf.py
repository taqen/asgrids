import pandas as pd
import matplotlib.pyplot as plt
from numpy import max, std, ceil, arange, sort, Inf
import numpy as np
from statsmodels.distributions.empirical_distribution import ECDF
import argparse
import os
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

args = parser.parse_args()
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

losses = [0, 5, 10, 15, 20, 40, 50, 60]
runs = [3, 4, 5, 6, 7]#[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
width=0.4
data_opf: dict = {}
data_pi: dict = {}
for j in losses:
    data_opf[j] = []
    data_pi[j] = []
    for i in runs:
        try:
            if with_opf:
                print("reading for opf {}% loss: {}".format(j, i))
                data = pd.read_csv(os.path.join(results, 'sim_opf_{}loss_5.{}.log'.format(j,i)), header=None, delimiter='\t')
                data.drop(data[data[0].str.contains('LOAD')].index, inplace=True)
                data[0]=data[0].str.replace('VOLTAGE ', '')
                data[0]=pd.to_numeric(data[0],errors='coerce')
                data.reset_index(drop=True, inplace=True)
                data[0]=data[0]-data.loc[0,0]
                # data[0]=data[0].apply(ceil)
                # data.drop_duplicates(subset=[0,1], inplace=True, keep='last')
                # data.reset_index(drop=True, inplace=True)

                data.drop(data[data[0]>287].index, inplace=True)
                data.drop(data[data[0]==0].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                print("slicing for opf {}% loss: {}".format(j, i))
                # slicing
                data.drop(data[data[0]<tslice[0]].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                data.drop(data[data[0]>tslice[1]].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                data_opf[j] = data_opf[j] + data[2].tolist()
            if with_pi:
                print("reading for pi {}% loss: {}".format(j, i))
                data = pd.read_csv(os.path.join(results, 'sim_pi_{}loss_5.{}.log'.format(j,i)), header=None, delimiter='\t')
                data.drop(data[data[0].str.contains('LOAD')].index, inplace=True)
                data[0]=data[0].str.replace('VOLTAGE ', '')
                data[0]=pd.to_numeric(data[0],errors='coerce')
                data.reset_index(drop=True, inplace=True)
                data[0]=data[0]-data.loc[0,0]
                data.drop(data[data[0]>287].index, inplace=True)
                data.drop(data[data[0]==0].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                # slicing
                print("slicing for pi {}% loss: {}".format(j, i))
                data.drop(data[data[0]<tslice[0]].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                data.drop(data[data[0]>tslice[1]].index, inplace=True)
                data.reset_index(drop=True, inplace=True)
                data_pi[j] = data_pi[j] + data[2].tolist()
        except Exception as e:
            print(e)

print("reading for no control")
data = pd.read_csv(os.path.join(results, 'sim_no_control.log'), header=None, delimiter='\t')
data[0]=data[0]-data.loc[0,0]
data.drop(data[data[0]>287].index, inplace=True)
data.drop(data[data[0]==0].index, inplace=True)
data.reset_index(drop=True, inplace=True)
print("slicing for no control")
data.drop(data[data[0]<tslice[0]].index, inplace=True)
data.reset_index(drop=True, inplace=True)
data.drop(data[data[0]>tslice[1]].index, inplace=True)
data.reset_index(drop=True, inplace=True)

data_pv =  data[2].tolist()
ecdf_pv = ECDF(data_pv)

for j in losses:
    ecdf_opf = ECDF(data_opf[j])
    if with_pi:
        ecdf_pi = ECDF(data_pi[j])

    fig = plt.figure()
    ax = fig.add_subplot(111)
    if with_opf:
        x = [i for i in arange(0.98, max(data_opf[j]), 0.001)]
        y = ecdf_opf(x)
        plot_opf = ax.plot(x, y, color="blue")
    if with_pi:    
        x = [i for i in arange(0.98, max(data_pi[j]), 0.001)]
        y = ecdf_pi(x)
        plot_pi = ax.plot(x, y, color="magenta")
    x = [i for i in arange(0.98, max(data_pv), 0.001)]
    y = ecdf_pv(x)
    plot_pv = ax.plot(x, y, color="red")
        
    #------------------------------------------------------------------
    if with_opf:
        ax.plot([1.01, 1.01], sort([ecdf_opf(1.01), ecdf_pv(1.01)]), marker='d', color='black')
    if with_pi:
        ax.plot([1.01], [ecdf_pi(1.01)], marker='d', color='black')
    ax.plot([1.01, 1.01], [0, 1], '--', color='black')

    bbox = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    if with_opf:
        ax.text(1.015, ecdf_opf(1.01)+0.01, "OPF: %0.2f"%ecdf_opf(1.01), bbox=bbox, fontsize=8)
    if with_pi:
        ax.text(1.015, ecdf_pi(1.01), "PI: %0.2f"%ecdf_pi(1.01), bbox=bbox, fontsize=8)
    ax.text(1.015, ecdf_pv(1.01)-0.01, "NC: %0.2f"%ecdf_pv(1.01), bbox=bbox, fontsize=8)
    #------------------------------------------------------------------
    
    #------------------------------------------------------------------
    if with_opf:
        ax.plot([1.0, 1.0], sort([ecdf_opf(1.0), ecdf_pv(1.0)]), marker='d', color='black')
    if with_pi:
        ax.plot([1.0], sort([ecdf_pi(1.0)]), marker='d', color='black')

    ax.plot([1.0, 1.0], [0, 1], '--', color='black')

    bbox = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    if with_opf:
        ax.text(1.005, ecdf_opf(1.0)+0.03, "OPF: %0.2f"%ecdf_opf(1.0), bbox=bbox, fontsize=8)
    if with_pi:
        ax.text(1.005, ecdf_pi(1.0), "PI: %0.2f"%ecdf_pi(1.0), bbox=bbox, fontsize=8)
    ax.text(1.005, ecdf_pv(1.0)-0.03, "NC: %0.2f"%ecdf_pv(1.0), bbox=bbox, fontsize=8)
    #------------------------------------------------------------------
    xticks = ax.get_xticks()
    xticks = np.append(xticks, 1.01)
    ax.set_xticks(xticks)
    ax.set_xlabel("vm (p.u.)")
    ax.set_ylabel("ecdf")
    legend_items = [plot_pv[0]]
    if with_opf:
        legend_items = [plot_opf[0]] + legend_items
    if with_pi:
        legend_items = [plot_pi[0]] + legend_items
    legend_labels = ["No Control(NC)"]
    if with_opf:
        legend_labels = ["OPF Control"] + legend_labels
    if with_pi:
        legend_labels = ["PI Control"] + legend_labels
    ax.legend(legend_items, legend_labels)

    plt.tight_layout()
    plt.savefig('ecdf_%dloss.png'%j, dpi=600)
# plt.show()