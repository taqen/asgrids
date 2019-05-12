tc qdisc add dev lo root handle 1: prio bands 9 priomap 8 8 8 8 8 8 8 8 8 8 8 8 8 8 8 8
tc qdisc add dev lo parent 1:1 handle 10: netem loss 30%
tc qdisc add dev lo parent 1:2 handle 11: netem loss 40%
tc qdisc add dev lo parent 1:3 handle 12: netem loss 50%
tc qdisc add dev lo parent 1:4 handle 13: netem loss 60%

# tc filter add dev lo protocol ip parent 1:0 prio 1 u32 match ip dst 127.0.1.1/24 flowid 1:1
tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dst 127.0.2.1/24 flowid 1:1
tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dst 127.0.3.1/24 flowid 1:2
tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dst 127.0.4.1/24 flowid 1:3
tc filter add dev lo protocol ip parent 1: prio 1 u32 match ip dst 127.0.5.1/24 flowid 1:4
