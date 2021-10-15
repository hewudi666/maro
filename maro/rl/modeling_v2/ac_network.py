from abc import ABCMeta, abstractmethod
from typing import Tuple

import torch
from torch.distributions import Categorical

from .base_model import DiscretePolicyNetworkMixin, PolicyNetwork


class QCriticMixin:
    @abstractmethod
    def q_critic(self, states: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """
        Args:
            states: [batch_size, state_dim]
            actions: [batch_size, action_dim]

        Returns:
            q values for critic: [batch_size]
        """
        pass


class VCriticMixin:
    @abstractmethod
    def v_critic(self, states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            states: [batch_size, state_dim]

        Returns:
            v values for critic: [batch_size]
        """
        pass


class DiscreteActorCriticNet(DiscretePolicyNetworkMixin, PolicyNetwork, metaclass=ABCMeta):
    def __init__(self, state_dim: int, action_num: int) -> None:
        super(DiscreteActorCriticNet, self).__init__(state_dim=state_dim, action_dim=1)
        self._action_num = action_num

    @property
    def action_num(self) -> int:
        return self._action_num

    def get_actions_exploration(self, states: torch.Tensor) -> torch.Tensor:
        return self.get_actions_and_logps(states)[0]

    def get_actions_exploitation(self, states: torch.Tensor) -> torch.Tensor:
        return self.get_actions_and_logps_greedy(states)[0]

    def get_actions_and_logps_exploration(self, states: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        action_probs = Categorical(self.get_probs(states))
        actions = action_probs.sample()
        logps = action_probs.log_prob(actions)
        return actions, logps


class DiscreteQActorCriticNet(QCriticMixin, DiscreteActorCriticNet):
    def __init__(self, state_dim: int, action_num: int) -> None:
        super(DiscreteQActorCriticNet, self).__init__(state_dim=state_dim, action_num=action_num)

    def q_critic(self, states: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        q_matrix = self.q_critic_for_all_actions(states)  # [batch_size, action_num]
        actions = actions.unsqueeze(dim=1)
        return q_matrix.gather(dim=1, index=actions).reshape(-1)

    @abstractmethod
    def q_critic_for_all_actions(self, states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            states: [batch_size, state_dim]

        Returns:
            q values for all actions: [batch_size, action_num]
        """
        pass


class DiscreteVActorCriticNet(VCriticMixin, DiscreteActorCriticNet, metaclass=ABCMeta):
    def __init__(self, state_dim: int, action_num: int) -> None:
        super(DiscreteVActorCriticNet, self).__init__(state_dim=state_dim, action_num=action_num)
