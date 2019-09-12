#!/usr/bin/env python
"""
Run a correlation structure calculation
"""

import correlation_structure.run_config as rc
import sys
import glob
import random
import json

# Store all of the tprs in a single directory: ensemble_dir/tprs/
ensemble_dir = "/home/jennifer/test-brer"
tprs = glob.glob("{}/tprs/*.tpr".format(ensemble_dir))

# Load the history of targets + alphas
history = json.load(open("{}/history.json".format(ensemble_dir)))

""" Select a tpr. 
If the simulation is in the convergence or production phase already, there will
be a checkpoint in that directory. That means the random selection of a tpr won't
cause a change in state. However, if the simulation is just *starting* a convergence
run, the random selection *will* have an effect, because there is no cpt in the 
directory.
"""
tpr = random.choice(tprs)

# Initialize the run
init = {
    'tpr': tpr,
    'ensemble_dir': ensemble_dir,
    'ensemble_num': 1,
    'pairs_json': '/home/jennifer/Git/run_brer/run_brer/data/pair_data.json'
}
config = rc.RunConfig(**init)

config.run_data.set(A=100, history=history)

config.run()

# Update the ensemble history.
single_simulation_history = config.run_data.history.get_as_dictionary()
for elem in single_simulation_history:
    if elem not in history:
        history[elem] = single_simulation_history[elem]

json.dump(history, open("{}/history.json".format(ensemble_dir), "w"))
    