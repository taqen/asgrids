import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import pandapower.networks as pn

net = pn.create_cigre_network_lv()
results = [1, 2, 6, 7, 8, 9]

ids = ['bus_2', 'bus_12', 'bus_16', 'bus_17', 'bus_18', 'bus_19', 'bus_22', 'bus_24',
        'bus_35', 'bus_36', 'bus_37', 'bus_40', 'bus_41', 'bus_42', 'bus_43',
        'load_127.0.0.1:5566', 'load_127.0.0.1:5564', 'load_127.0.0.1:5585',
        'load_127.0.0.1:5568', 'load_127.0.0.1:5574', 'load_127.0.0.1:5584',
        'load_127.0.0.1:5576', 'load_127.0.0.1:5572', 'load_127.0.0.1:5560',
        'load_127.0.0.1:5558', 'load_127.0.0.1:5575', 'load_127.0.0.1:5561',
        'load_127.0.0.1:5578', 'load_127.0.0.1:5581', 'load_127.0.0.1:5569',
        'load_127.0.0.1:5563', 'load_127.0.0.1:5570', 'load_127.0.0.1:5556',
        'load_127.0.0.1:5562', 'load_127.0.0.1:5567', 'load_127.0.0.1:5582',
        'load_127.0.0.1:5579', 'load_127.0.0.1:5565', 'load_127.0.0.1:5557',
        'load_127.0.0.1:5573', 'load_127.0.0.1:5583', 'load_127.0.0.1:5577',
        'load_127.0.0.1:5571', 'load_127.0.0.1:5559', 'load_127.0.0.1:5580']

width = 2
interwidth = 5

# Plot Bus voltages
for bid in ids:
    if 'bus' not in bid:
        continue
    fig = plt.figure()
    ax = fig.add_subplot(111)

    pi: list = []
    opf: list = []
    data = pd.read_csv('sim_pv.log', header=None, delimiter='\t')
    pv = data[(data[1]==bid) & (data[2] >= 1.05)].size
    if pv == 0:
        continue
    print(net.bus['name'][int(bid.split('_')[1])])
    pv_plot = ax.plot([i for i in range(interwidth*len(results))], [pv for i in range(interwidth*len(results))], 'r--')
    for i in results:
        data = pd.read_csv('sim_pi_%d.log'%(i), header=None, delimiter='\t')
        pi = pi + [data[(data[1]==bid) & (data[2] >= 1.05)].size]
        data = pd.read_csv('sim_opf_%d.log'%(i), header=None, delimiter='\t')
        opf = opf + [data[(data[1]==bid) & (data[2] >= 1.05)].size]
    pi_bar = ax.bar([i*interwidth for i in range(len(results))], pi, width=width, color='yellow', alpha=1)
    opf_bar = ax.bar([i*interwidth+width for i in range(len(results))], opf, width=width, color='b', alpha=1)
    
    # place text in bars
    for idx,rect in enumerate(pi_bar):
        height = rect.get_height()
        ax.text(rect.get_x() + rect.get_width()/2., 0.25*height,
        '{:10.2f}% less'.format((pv-rect.get_height())*100/pv),
        ha='center', va='bottom', rotation=90, fontsize=6)
        ax.text(rect.get_x() + rect.get_width()/2., 1.05*height,
        height,
        ha='center', va='bottom', rotation=0, fontsize=6)

    for idx,rect in enumerate(opf_bar):
        #place improvement in % inside
        height = rect.get_height()
        ax.text(rect.get_x() + rect.get_width()/2., 0.25*height,
        '{:10.2f}% less'.format((pv-rect.get_height())*100/pv),
        ha='center', va='bottom', color='w', rotation=90, fontsize=6)
        # place value on top
        ax.text(rect.get_x() + rect.get_width()/2., 1.05*height,
        height, ha='center', va='bottom', rotation=0, fontsize=6)


    ax.set_xticks([i*interwidth+1 for i in range(len(results))])
    # ax.set_yticks([i*10 for i in range(10)])
    ax.set_xticklabels(['%ds'%(i) for i in results])
    # ax.set_yticklabels(['%d%%'%(i*10) for i in range(10)])
    ax.legend( (pi_bar[0], opf_bar[0], pv_plot[0]), ('PI', 'OPF', 'No Control'), loc='upper right', bbox_to_anchor=(1, 0.95), fontsize=6)
    plt.title(net.bus['name'][int(bid.split('_')[1])])
    fig.savefig('voltage_bypass_%s.png'%bid, dpi=300)

# # Plot load profiles
# for lid in ids:
#     if 'load' not in bid:
#         continue
#     fig = plt.figure()
#     ax = fig.add_subplot(111)

#     data = pd.read_csv('sim_pv.log', header=None, delimiter='\t')
#     pv_plot = ax.plot(data[data[1]==lid][0]-data[0][0], data[2], 'r--')
#     for i in results:
#         data = pd.read_csv('sim_pi_%d.log'%(i), header=None, delimiter='\t')
#         pi_plot = ax.plot(data[data[1]==lid][0]-data[0][0], data[2], '-.')
#         data = pd.read_csv('sim_opf_%d.log'%(i), header=None, delimiter='\t')
#         opf_plot = ax.plot(data[data[1]==lid][0]-data[0][0], data[2], ':')
#     ax.legend( (pi_bar[0], opf_bar[0], pv_plot[0]), ('PI', 'OPF', 'No Control'), loc='upper right', bbox_to_anchor=(1, 0.95), fontsize=6)
