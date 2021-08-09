# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import yaml
from copy import deepcopy
from os.path import dirname, join, realpath

path = realpath(__file__)
docker_script_dir = dirname(path)
rl_example_dir = dirname(dirname(docker_script_dir))
root_dir = dirname(dirname(rl_example_dir))
workflow_dir = join(rl_example_dir, "workflows")
maro_rl_dir = join(root_dir, "maro", "rl")
maro_sc_dir = join(root_dir, "maro", "simulator", "scenarios", "supply_chain")
config_path = join(workflow_dir, "config.yml")
dockerfile_path = join(root_dir, "docker_files", "dev.df")

with open(config_path, "r") as fp:
    config = yaml.safe_load(fp)
    num_trainers = config["policy_manager"]["num_trainers"]
    redis_host = config["redis"]["host"]

docker_compose_manifest = {"version": "3.9", "services": {"redis": {"image": "redis:6", "container_name": redis_host}}}
common_spec = {
    "build": {"context": root_dir, "dockerfile": dockerfile_path},
    "image": "marorl",
    "volumes": [
        f"{rl_example_dir}:/maro/rl_examples",
        f"{maro_rl_dir}:/maro/maro/rl",
        f"{maro_sc_dir}:/maro/maro/simulator/scenarios/supply_chain"    
    ]
}

common_env = [
    f"REDISHOST={config['redis']['host']}",
    f"REDISPORT={config['redis']['port']}",
    f"JOB={config['job']}",
    f"SCENARIO={config['scenario']}",
    f"MODE={config['mode']}",
    f"EXPDIST={'1' if config['rollout_experience_distribution'] else '0'}"
]

if config["mode"] == "sync":
    common_env.append(f"NUMWORKERS={config['sync']['num_rollout_workers']}")
else:
    common_env.append(f"NUMACTORS={config['async']['num_actors']}")

# trainer spec
if config["policy_manager"]["train_mode"] == "multi-node":
    for trainer_id in range(num_trainers):
        str_id = f"trainer.{trainer_id}"
        trainer_spec = deepcopy(common_spec)
        del trainer_spec["build"]
        trainer_spec["command"] = "python3 /maro/rl_examples/workflows/policy_manager/trainer.py"
        trainer_spec["container_name"] = str_id
        trainer_spec["environment"] = [
            f"TRAINERID={trainer_id}",
            f"TRAINGROUP={config['policy_manager']['train_group']}"
        ] + common_env
        docker_compose_manifest["services"][str_id] = trainer_spec

mode = config["mode"]
if mode == "sync":
    # learner_spec
    docker_compose_manifest["services"]["learner"] = {
        **common_spec, 
        **{
            "container_name": "learner",
            "command": "python3 /maro/rl_examples/workflows/synchronous/learner.py",
            "environment": [
                f"ROLLOUTMODE={config['sync']['rollout_mode']}",
                f"NUMSTEPS={config['num_steps']}",
                f"MAXLAG={config['max_lag']}",
                f"MINFINISH={config['sync']['min_finished_workers']}",
                f"MAXEXRECV={config['sync']['max_extra_recv_tries']}",
                f"MAXRECVTIMEO={config['sync']['extra_recv_timeout']}",
                f"ROLLOUTGROUP={config['sync']['rollout_group']}",
                f"NUMEPISODES={config['num_episodes']}",
                f"EVALSCH={config['eval_schedule']}",
                f"TRAINMODE={config['policy_manager']['train_mode']}",
                f"TRAINGROUP={config['policy_manager']['train_group']}",
                f"NUMTRAINERS={config['policy_manager']['num_trainers']}"
            ] + common_env
        }
    }
    # rollout worker spec
    if config["sync"]["rollout_mode"] == "multi-node":
        for worker_id in range(config["sync"]["num_rollout_workers"]):
            str_id = f"rollout_worker.{worker_id}"
            worker_spec = deepcopy(common_spec)
            del worker_spec["build"]
            worker_spec["command"] = "python3 /maro/rl_examples/workflows/synchronous/rollout_worker.py"
            worker_spec["container_name"] = str_id
            worker_spec["environment"] = [
                f"WORKERID={worker_id}",
                f"ROLLOUTGROUP={config['sync']['rollout_group']}",
                f"EVALSCH={config['eval_schedule']}"
            ] + common_env
            docker_compose_manifest["services"][str_id] = worker_spec
elif mode == "async":
    # policy server spec
    docker_compose_manifest["services"]["policy_server"] = {
        **common_spec, 
        **{
            "container_name": "policy_server",
            "command": "python3 /maro/rl_examples/workflows/asynchronous/policy_server.py",
            "environment": [
                f"GROUP={config['async']['group']}",
                f"MAXLAG={config['max_lag']}"
            ] + common_env
        }
    }
    # actor spec
    for actor_id in range(config["async"]["num_actors"]):
        str_id = f"actor.{actor_id}"
        actor_spec = deepcopy(common_spec)
        del actor_spec["build"]
        actor_spec["command"] = "python3 /maro/rl_examples/workflows/asynchronous/actor.py"
        actor_spec["container_name"] = str_id
        actor_spec["environment"] = [
            f"ACTORID={actor_id}",
            f"GROUP={config['async']['group']}",
            f"NUMEPISODES={config['num_episodes']}",
            f"NUMSTEPS={config['num_steps']}",
            f"EVALSCH={config['eval_schedule']}"
        ] + common_env
        docker_compose_manifest["services"][str_id] = actor_spec
else: 
    raise ValueError(f"mode must be 'sync' or 'async', got {mode}")

with open(join(docker_script_dir, "docker-compose.yml"), "w") as fp:
    yaml.safe_dump(docker_compose_manifest, fp)
