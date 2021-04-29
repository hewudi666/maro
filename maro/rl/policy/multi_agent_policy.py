# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import pickle
import warnings
from collections import namedtuple
from typing import Dict, Union

from maro.rl.exploration import AbsExploration, NullExploration
from maro.rl.experience import ExperienceMemory

from .policy import AbsFixedPolicy, AbsCorePolicy


class MultiAgentPolicy:
    """Convenience wrapper of a set of agents that exposes similar interfaces as a single agent.

    Args:
        
    """
    def __init__(
        self,
        policy_dict: Dict[str, Union[AbsFixedPolicy, AbsCorePolicy]],
        agent_to_policy: Dict[str, str],
        exploration_dict: Dict[str, AbsExploration] = None,
        agent_to_exploration: Dict[str, str] = None
    ):
        self.policy_dict = policy_dict
        self.agent_to_policy = agent_to_policy
        self.policy = {
            agent_id: self.policy_dict[policy_id] for agent_id, policy_id in self.agent_to_policy.items()
        }

        self.exploration_dict = exploration_dict
        if exploration_dict:
            self.agent_to_exploration = agent_to_exploration
            self.exploration = {
                agent_id: self.exploration_dict[exploration_id]
                for agent_id, exploration_id in self.agent_to_exploration.items()
            }
            self.with_exploration = True

    def train_mode(self):
        self.with_exploration = True

    def eval_mode(self):
        self.with_exploration = False

    @property
    def exploration_params(self):
        if hasattr(self, "exploration"):
            return {agent_id: exploration.parameters for agent_id, exploration in self.exploration.items()}

    def choose_action(self, state_by_agent: dict):
        if self.exploration_dict and self.with_exploration:      
            return {
                agent_id:
                    self.exploration[agent_id](self.policy[agent_id].choose_action(state))
                    if agent_id in self.exploration else self.policy[agent_id].choose_action(state)
                for agent_id, state in state_by_agent.items()
            }

        return {agent_id: self.policy[agent_id].choose_action(state) for agent_id, state in state_by_agent.items()}

    def on_new_experiences(self, experiences_by_agent: dict):
        for agent_id, exp in experiences_by_agent.items():
            if isinstance(self.policy[agent_id], AbsCorePolicy):
                self.policy[agent_id].store_experiences(exp)

        return [
            policy_id for policy_id, policy in self.policy_dict.items()
            if isinstance(policy, AbsCorePolicy) and policy.learn()
        ]

    def update(self, policy_dict: dict):
        """Load policies from memory."""
        if not policy_dict.keys() <= self.policy_dict.keys():
            raise Exception(f"Expected policies from {list(self.policy_dict.keys())}")

        for policy_id, policy in policy_dict.items():
            self.policy_dict[policy_id].update(policy)

    def exploration_step(self):
        if self.exploration_dict:
            for exploration in self.exploration_dict.values():
                exploration.step()

    def load(self, dir_path: str):
        """Load models from disk."""
        for policy_id, policy in self.policy_dict.items():
            try:
                policy.load(os.path.join(dir_path, policy_id))
            except FileNotFoundError:
                warnings.warn(f"policy {policy_id} is skipped because no file is found")

    def save(self, dir_path: str):
        os.makedirs(dir_path, exist_ok=True)
        for policy_id, policy in self.policy_dict.items():
            policy.save(os.path.join(dir_path, policy_id))
