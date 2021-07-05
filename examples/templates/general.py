# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import sys
import yaml
from os.path import dirname, join, realpath

template_dir = dirname(realpath(__file__)) 
example_dir = dirname(template_dir)
if template_dir not in sys.path:
    sys.path.insert(0, template_dir)
if example_dir not in sys.path:
    sys.path.insert(0, example_dir)

config_path = join(template_dir, "config.yml")
with open(config_path, "r") as config_file:
    config = yaml.safe_load(config_file)

log_dir = join(example_dir, "logs", config["job_name"])

scenario = config["scenario"]
if scenario == "cim":
    from cim.env_wrapper import get_env_wrapper
    from cim.agent_wrapper import get_agent_wrapper
    from cim.policy_index import rollout_policy_func_index, train_policy_func_index
else:
    raise ValueError(f"Unsupported scenario: {scenario}. Supported scenarios: 'cim'")
