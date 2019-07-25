#%% Change working directory from the workspace root to the ipynb file location. Turn this addition off with the DataScience.changeDirOnImportExport setting
# ms-python.python added
import os
try:
        os.chdir('./')
        print(os.getcwd())
except:
        pass

#%%
from pylab import *
import pandas as pd
from pandas.api.types import is_string_dtype


#%%
total_pv = 35970.01922997645
max_vm = 1.05

def calculate_rate(data):
    data = filter_data(data, drop='LOAD')
    data = data.reset_index(drop=True)
    data = data[data[2]>=max_vm][2].count()/data[2].count()
    return data

def filter_data(data, drop):
    keep = 'VOLTAGE ' if drop == 'LOAD' else 'LOAD '
    if is_string_dtype(data[0]):
        data = data.drop(data[data[0].str.contains(drop)].index)
        data[0]=data[0].str.replace(keep, '')
        data[0]=pd.to_numeric(data[0],errors='coerce')
        data = data.reset_index(drop=True)
    data[0]=data[0]-data.loc[0,0]
    data = data.drop(data[data[0]>200].index)
    return data

def get_power_loss(data):
    data = filter_data(data, drop='VOLTAGE')
    total = 0
    data = data.groupby(1)
    for name, g in data:
        value = sum(g[2])
        if value <=0:
            total = total + sum(g[2])
    data = 1-abs(total)/total_pv
    print(data)
    return [data]


#%%
curve = pd.read_csv('curves.csv')
name_to_addr = ['PV_Load R1_P', 'PV_Load R11_P',
       'PV_Load R15_P', 'PV_Load R16_P',
       'PV_Load R17_P', 'PV_Load R18_P',
       'PV_Load I2_P', 'PV_Load C1_P',
       'PV_Load C12_P', 'PV_Load C13_P',
       'PV_Load C14_P', 'PV_Load C17_P',
       'PV_Load C18_P', 'PV_Load C19_P',
       'PV_Load C20_P']

def plot_data_gp(name, node, drop):
    data = pd.read_csv(name, header=None, delimiter='\t')
    print("{}%".format(100*calculate_rate(data)))
    data = filter_data(data, drop)
    data_gb = data.groupby(1)    
    i = 0
    for name, g in data_gb:
        # fig = plt.figure()
        value = sum(g[2])
        if value < 0:
            if name_to_addr[i] != node:
                i += 1
                continue
            fig = plt.figure()
            plt.plot(abs(curve[name_to_addr[i]]),'--')
            plt.title(name_to_addr[i])
            plt.plot(np.array(53+g[0]-g.iloc[0,0]), abs(np.array(g[2])))
            i += 1
            # break
        #     plt.legend(('baseline', *name_to_addr))

def plot_voltage(name):
    data = pd.read_csv(name, header=None, delimiter='\t')
    print("{}%".format(100*calculate_rate(data)))        
    data = filter_data(data, drop='LOAD')
    # data = data.drop(data[~data[1].str.contains(node)].index)
    fig = plt.figure()
    for bid in data[1].unique():
        plt.plot(np.array(53+data[data[1]==bid][0]-data.iloc[0,0]), abs(np.array(data[data[1]==bid][2])))
#%%
name = "../results_2/tcp/sim.opf.127.0.0.1loss.1.log"
#%%
plot_data_gp(name, node='PV_Load C20_P', drop='VOLTAGE')
#%%
plot_voltage(name)

# plt.show()
#%%
plt.close()
#%%

#%%
data = pd.read_csv(name, header=None, delimiter='\t')
# get_power_loss(data)
100*calculate_rate(data)

#%%
