#%%
import pandas as pd
import matplotlib.pyplot as plt
import pandapower as pp
#%%
ids = ['127.0.0.1:55%i'%(i+1) for i in range(55, 85)]
bids = ['bus_2', 'bus_12', 'bus_16', 'bus_17', 'bus_18', 'bus_19', 'bus_22', 'bus_24',
        'bus_35', 'bus_36', 'bus_37', 'bus_40', 'bus_41', 'bus_42', 'bus_43']

real_ids = ['Load R1', 'Load R11', 'Load R15', 'Load R16', 'Load R17', 'Load R18', 
            'Load I2', 'Load C1', 'Load C12', 'Load C13', 'Load C14', 'Load C17', 
            'Load C18', 'Load C19', 'Load C20', 'PV_Load R1', 'PV_Load R11', 
            'PV_Load R15', 'PV_Load R16', 'PV_Load R17', 'PV_Load R18', 
            'PV_Load I2', 'PV_Load C1', 'PV_Load C12', 'PV_Load C13', 
            'PV_Load C14', 'PV_Load C17', 'PV_Load C18', 'PV_Load C19', 'PV_Load C20']

net = pp.from_json('../victor_scripts/cigre/cigre_network_lv.json')

def get_bid(lid):
    return net.load[net.load['name']==lid]['bus'].item()
def get_bid_name(bid):
    return net.bus.loc[int(bid.split('_')[1]), 'name']
def get_lids(bid):
    return net.load[net.load['bus'] == int(bid.split('_')[1])]['name'].tolist()
def get_simlid(lid):
    if lid in ids:
        return ids.index[real_ids(lid)]

for bid in bids:
    lids = get_lids(bid)
    voltages=pd.DataFrame({0:[], 4:[]})
    for i in range(10):
        data = pd.read_csv('experiments/3/sim_pv_%d.log'%(i+1), header=None, delimiter='\t')
        data[0] = data[0]-data.loc[0,0]
        data = data[data[1].isin(lids)]
        voltages = pd.concat([voltages, data[[0, 4]]], axis=0, ignore_index=True)
    voltages.sort_values(by=[0])
    data_cut = pd.cut(voltages[0], [i for i in range(300)])
    data_group = voltages.groupby(data_cut)
    pv_grouped:list = []
    for name, group in data_group:
        pv_grouped.append(group[4].dropna().mean())

    opf_grouped: list = []
    pi_grouped: list = []
    for i in range(10):
        voltages=pd.DataFrame({0:[], 4:[]})
        opf_grouped.append([])
        for j in range(10):
            data = pd.read_csv('experiments/3/sim_opf_{}.{}.log'.format(j+1, i+1), header=None, delimiter='\t')
            data[0] = data[0]-data.loc[0,0]
            data = data[data[1].isin(lids)]
            voltages = pd.concat([voltages, data[[0, 4]]], axis=0, ignore_index=True)
        voltages.sort_values(by=[0])
        data_cut = pd.cut(voltages[0], [i for i in range(300)])
        data_group = voltages.groupby(data_cut)
        for name, group in data_group:
            opf_grouped[i].append(group[4].dropna().mean())

    for i in range(10):
        voltages=pd.DataFrame({0:[], 4:[]})
        pi_grouped.append([])
        for j in range(10):
            data = pd.read_csv('experiments/3/sim_pi_{}.{}.log'.format(j+1, i+1), header=None, delimiter='\t')
            data[0] = data[0]-data.loc[0,0]
            data = data[data[1].isin(lids)]
            voltages = pd.concat([voltages, data[[0, 4]]], axis=0, ignore_index=True)
        voltages.sort_values(by=[0])
        data_cut = pd.cut(voltages[0], [i for i in range(300)])
        data_group = voltages.groupby(data_cut)
        for name, group in data_group:
            pi_grouped[i].append(group[4].dropna().mean())

    medianprops = dict(linestyle='-.', linewidth=2.5)
    for i in range(10):
        fig = plt.figure()
        ax = fig.add_subplot(111)
        pv_plot=ax.plot([i for i in range(len(pv_grouped))],pv_grouped, 'r-')
        opf_plot=ax.plot([i for i in range(len(opf_grouped[i]))],opf_grouped[i], 'b-')
        pi_plot=ax.plot([i for i in range(len(pi_grouped[i]))],pi_grouped[i], '-', color='yellow')
        
        ax.plot([0, 290], [1.05, 1.05], 'r--')
        ax.plot([0, 290], [0.95, 0.95], 'r--')
        ax.set_ylim(0.953, 1.07)
        ax.set_xlabel('Time(s)')
        ax.set_ylabel('vm (p.u.)')
        ax.legend((pv_plot[0], opf_plot[0], pi_plot[0]), ('No Control', 'OPF Control', 'PI Control'))
        ax.set_ylim(0.953, 1.07)
        plt.savefig('sim_boxplot_{}.{}.png'.format(get_bid_name(bid), i+1), dpi=300)
        plt.close()
# plt.show()