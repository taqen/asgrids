# About
**asgrids** is an **a**synchronous **s**mart **gri**ds **d**istributed **s**imulator. It provides an environment to describe a multi-model smart-grid network, in terms of electrical/communication topology, plus control logic and behavior of its sensors, actuators and components.

The project is still under development and the code is therefore experimental, and is released under a GPL-3.0 license, which is given in the ``LICENSE`` file.

# Requirements
- Python 3.6 and higher.

# Installation
To install, simply do:

``python setup.py install``

Or (preferably) setup locally to reflect modifications without needing rebuilding:

``python setup.py develop``

# APEEC 2019 Repository Overview
This repository provides training and testing code and data for IEEE APPEEC 2019 paper:

"ASGriDS: **A**synchronous **S**mart **Gri**ds **D**istributed **S**imulator"

# Setup
- [asgrids](https://github.com/takienn/asgrids): 
```bash
git clone -b appeec19 --single-branch https://github.com/takienn/asgrids.git
```
- [`psrecord`](https://github.com/astrofrog/psrecord):
```bash
pip install https://github.com/astrofrog/psrecord/archive/v1.1.tar.gz
```

<a id="appeec"></a>
# Generating Results
The results consist of performance/scalability measurements, and a use case scenario, as described in the paper.
<a id="perf"></a>
## Performance Measurements
We perform CPU/MEM measurements by running the script in `./examples/large_grid_example`, using [`psrecord`](https://github.com/astrofrog/psrecord) to log realtime CPU and memory usage, with different network sizes as follows:
```bash
for i in 10 20 50 100 300 500 1000; 
do psrecord --include-children --log ps.${i}.out "python large_grid_example.py --pp --sim-time 30 --pp-cycle 0 --case case300 --nodes $i"; 
done
```

<a id="cigre"></a>
## CIGRE LV scenario
The scenario is implemented in simulation script `./examples/cigre_pv_example.py`.
The script will deploy a CIGRE LV network as implemented in `pandapower`, along with a power flow analyzer and optimal power flow solver as described in our paper.
To run multiple simulation campaigns, the script is executed as follows:

```bash
for run in 1 2 3 4 5 6 7 8 9 10; 
do for address in "127.0.0.1" "127.0.2.1" "127.0.3.1" "127.0.4.1" "127.0.5.1"; 
do for mode in "tcp" "udp"; 
do taskset -c 0 python cigre_pv_example.py --initial-port 5000 --with-pv --optimize --optimize-cycle 3 --optimizer opf --address $address --max-vm 1.05 --mode $mode --output "./results/${mode}/sim.${optimizer}.${address}loss.${run}.log"; 
done; 
done;
done
```

Assuming that local interfaces: 127.0.0.1, 127.0.2.1, 127.0.3.1, 127.0.4.1, 127.0.5.1 are configure with `netem` through `./examples/create_netem.sh` to exhibit the packet losses: 0%, 10%, 20%, 30%, 60% consecutively.

# Processing Results
## Performance Measurements
To generate the plot, we run the script `./examples/plot_memory.py` in the same folder as the generated results.

**Note**

This script assumes that the results are stored in the same folder in the format above

## CIGRE LV Scenario
Plotting the results will rely on two scripts: 

1. `./examples/plot_loss_com.py`: to generate voltage violates per packet loss rate figure.
The figures in the paper are generated with this configuration:
```bash
python plot_loss_com.py --runs 1 2 3 4 5 6 7 8 9 10 --losses 0 10 20 30 60 --output bars_loss.png --results ./results/ --width 0.5 --figsize 8 4
```
2. `./examples/plot_prod_com.py`: to generate production loss rate per packet loss rate figure.
The figures in the paper are generated with this configuration:
```bash
python plot_prod_com.py --runs 1 2 3 4 5 6 7 8 9 10 --losses 0 10 20 30 60 --output bars_loss.png --results ./results/ --width 0.5 --figsize 8 4
```
    
    
It is possible to save the process data for quick reuse to tune/tweak the plot, by provided `--save data.pkl` during a first run, the loading with `--load data.pkl` in later runs. Runs, losses and figure size can also be selected and plotted individually or in any configuration by playing the scripts arguments.

**Note**

- These two scripts assume that the results are stored in `./results/tcp` and `./results/udp` for tcp and udp data consecutively, in the format used above.
- The repository already contains paper results stored in ``loss_com.pkl`` and ``prod_com.pkl``, that can be loaded with the ``--load`` flag for faster re-generating of plots.
