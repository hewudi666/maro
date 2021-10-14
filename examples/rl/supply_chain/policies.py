# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os
import sys

import numpy as np
import scipy.stats as st

from maro.rl.modeling import DiscreteQNet, FullyConnected
from maro.rl.policy import DQN, AbsPolicy

sc_path = os.path.dirname(os.path.realpath(__file__))
if sc_path not in sys.path:
    sys.path.insert(0, sc_path)
from config import NUM_CONSUMER_ACTIONS, NUM_RL_POLICIES, dqn_conf, q_net_conf, q_net_optim_conf


######################################## DQN #################################################

class MyQNet(DiscreteQNet):
    def __init__(self):
        super().__init__()
        self.fc = FullyConnected(**q_net_conf)
        self.optim = q_net_optim_conf[0](self.fc.parameters(), **q_net_optim_conf[1])

    @property
    def input_dim(self):
        return q_net_conf["input_dim"]

    @property
    def num_actions(self):
        return q_net_conf["output_dim"]

    def forward(self, states):
        return self.fc(states)

    def step(self, loss):
        self.optim.zero_grad()
        loss.backward()
        self.optim.step()

    def get_gradients(self, loss):
        self.optim.zero_grad()
        loss.backward()
        return {name: param.grad for name, param in self.named_parameters()}

    def apply_gradients(self, grad):
        for name, param in self.named_parameters():
            param.grad = grad[name]

        self.optim.step()

    def get_state(self):
        return {"network": self.state_dict(), "optim": self.optim.state_dict()}

    def set_state(self, state):
        self.load_state_dict(state["network"])
        self.optim.load_state_dict(state["optim"])


######################################## Rule-based / OR #################################################

OR_STATE_OFFSET_INDEX = {
    "is_facility": 0,
    "sale_mean": 1,
    "sale_std": 2,
    "unit_storage_cost": 3,
    "order_cost": 4,
    "storage_capacity": 5,
    "storage_levels": 6,
    "consumer_in_transit_orders": 7,
    "product_idx": 8,
    "vlt": 9,
    "service_level": 10
}


def get_element(np_state, key):
    offsets = np_state[-len(OR_STATE_OFFSET_INDEX):]
    idx = OR_STATE_OFFSET_INDEX[key]
    prev_idx = offsets[idx - 1] if idx > 0 else 0
    return np_state[:, prev_idx : offsets[idx]].squeeze()


class DummyPolicy(AbsPolicy):
    def __call__(self, states):
        return [None] * states.shape[0]


class ProducerBaselinePolicy(AbsPolicy):
    def __call__(self, states):
        return 500 * np.ones(states.shape[0])


class ConsumerBaselinePolicy(AbsPolicy):
    def __call__(self, states):
        batch_size = len(states)
        res = np.random.randint(0, high=NUM_CONSUMER_ACTIONS, size=batch_size)
        # consumer_source_inventory
        available_inventory = get_element(states, "storage_levels")
        inflight_orders = get_element(states, "consumer_in_transit_orders")
        booked_inventory = available_inventory + inflight_orders
        most_needed_product_id = get_element(states, "product_idx")
        sale_mean, sale_std = get_element(states, "sale_mean"), get_element(states, "sale_std")
        service_level = get_element(states, "service_level")
        vlt_buffer_days = 7
        vlt = vlt_buffer_days + get_element(states, "vlt")

        non_facility_mask = ~(get_element(states, "is_facility").astype(np.bool))
        capacity_mask = np.sum(booked_inventory, axis=1) <= get_element(states, "storage_capacity")
        replenishment_mask = (
            booked_inventory[:, most_needed_product_id] <=
            vlt*sale_mean + np.sqrt(vlt) * sale_std * st.norm.ppf(service_level)
        )

        return res * (non_facility_mask & capacity_mask & replenishment_mask)


# Q = \sqrt{2DK/h}
# Q - optimal order quantity
# D - annual demand quantity
# K - fixed cost per order, setup cost (not per unit, typically cost of ordering and shipping and handling. This is not the cost of goods)
# h - annual holding cost per unit,
#     also known as carrying cost or storage cost (capital cost, warehouse space,
#     refrigeration, insurance, etc. usually not related to the unit production cost)
class ConsumerEOQPolicy(AbsPolicy):
    def _get_consumer_quantity(self, states):
        order_cost = get_element(states, "order_cost")
        holding_cost = get_element(states, "unit_storage_cost")
        sale_gamma = get_element(states, "sale_mean")
        consumer_quantity = np.sqrt(2 * sale_gamma * order_cost / holding_cost) / sale_gamma
        return consumer_quantity.astype(np.int32)

    def __call__(self, states):
        # consumer_source_inventory
        available_inventory = get_element(states, "storage_levels")
        inflight_orders = get_element(states, "consumer_in_transit_orders")
        booked_inventory = available_inventory + inflight_orders

        most_needed_product_id = get_element(states, "product_idx")
        sale_mean, sale_std = get_element(states, "sale_mean"), get_element(states, "sale_std")
        service_level = get_element(states, "service_level")
        vlt_buffer_days = 7
        vlt = vlt_buffer_days + get_element(states, "vlt")

        non_facility_mask = ~(get_element(states, "is_facility").astype(np.bool))
        # stop placing orders when the facilty runs out of capacity
        capacity_mask = np.sum(booked_inventory, axis=1) <= get_element(states, "storage_capacity")
        # whether replenishment point is reached
        replenishment_mask = (
            booked_inventory[:, most_needed_product_id] <=
            vlt*sale_mean + np.sqrt(vlt) * sale_std * st.norm.ppf(service_level)
        )
        return self._get_consumer_quantity(states) * (non_facility_mask & capacity_mask & replenishment_mask)


# parameters: (r, R), calculate according to VLT, demand variances, and service level
# replenish R - S units whenever the current stock is less than r
# S denotes the number of units in stock
class ConsumerMinMaxPolicy(AbsPolicy):
    def __call__(self, states):
        # consumer_source_inventory
        available_inventory = get_element(states, "storage_levels")
        inflight_orders = get_element(states, "consumer_in_transit_orders")
        booked_inventory = available_inventory + inflight_orders

        # stop placing orders if no risk of out of 
        most_needed_product_id = get_element(states, "product_idx")
        sale_mean, sale_std = get_element(states, "sale_mean"), get_element(states, "sale_std")
        service_level = get_element(states, "service_level")
        vlt_buffer_days = 10
        vlt = vlt_buffer_days + get_element(states, "vlt")
        r = vlt * sale_mean + np.sqrt(vlt) * sale_std * st.norm.ppf(service_level)
        # print(booked_inventory, most_needed_product_id, r)

        non_facility_mask = ~(get_element(states, "is_facility").astype(np.bool))
        # stop placing orders when the facilty runs out of capacity
        capacity_mask = np.sum(booked_inventory, axis=1) <= get_element(states, "storage_capacity")
        sales_mask = booked_inventory[:, most_needed_product_id] <= r
        R = 3 * r
        consumer_action = (R - r) / sale_mean
        return consumer_action.astype(np.int32) * (non_facility_mask & capacity_mask & sales_mask)


or_policy_func_dict = {
    # "consumer": lambda: ConsumerMinMaxPolicy(),
    "producer": lambda name: ProducerBaselinePolicy(name),
    "facility": lambda name: DummyPolicy(name),
    "product": lambda name: DummyPolicy(name),
    "productstore": lambda name: DummyPolicy(name)
}
policy_func_dict = {f"consumer-{i}": lambda name: DQN(name, MyQNet(), **dqn_conf) for i in range(NUM_RL_POLICIES)}
