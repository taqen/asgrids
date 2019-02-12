#!/usr/bin/env python
# -*- coding: utf-8 -*-

import itertools
import logging

import numpy as np

from .defs import Allocation

logger = logging.getLogger(__name__)


class PIController(object):
    """An object which generates allocations which can be sent to the load and generators nodes of a
    smart grid simulation.

    It is a Proportional Integral (PI) controller which only control generators. It also only limit the *active* power
    generation.
    """

    def __init__(self, maximum_voltage, sigma=5e-2, tau=4e-5, duration=10):
        """Constructor for PIController

        Args:
            maximum_voltage (float):
                The maximum voltage allowed in the network (in volts).

            sigma (float):
                The gain related to the proportional error (in volts^(-1)).

            tau (float):
                The gain related to the integral error (in (volt*seconds)^(-1)).

            duration (float):
                The duration (in seconds) of the generated allocations.
        """
        # A few basic checks
        if maximum_voltage < 0:
            msg = 'The maximum voltage must be positive: {}V provided.'.format(maximum_voltage)
            logger.error(msg)
            raise ValueError(msg)
        if sigma < 0 or sigma > 1:
            logger.warning('We strongly advise to use sigma in [0,1]: {:.3f} provided.'.format(sigma))
        if tau < 0 or tau > 1e-3:
            logger.warning('We strongly advise to use tau in [0,1e-3]. {:.3f} provided.'.format(tau))
        self.maximum_voltage = maximum_voltage
        self.sigma = sigma
        self.tau = tau
        self.duration = duration

        # Integral of the errors over time ( in V.s)
        self._lambda_error = 0.0

        # Allocator id generator
        self._count = itertools.count(start=0, step=1)

    def generate_allocations(self, load_voltages, generator_voltages, load_maximum_powers, generator_maximum_powers):
        """A method to generate the allocation to send to the loads and to the generators of the network.

        Args:
            load_voltages (List[float]):
                The list of voltages values (norms) for all load nodes (in volts).

            generator_voltages (List[float]):
                The list of voltages values (norms) for all generator nodes (in volts).

            load_maximum_powers (List[float]):
                The list of maximum (active) powers that can be consumed by the loads (in the same order as in the
                voltage array).

            generator_maximum_powers (List[float]):
                The list of maximum (active) powers that can be produced by the generators (in the same order as in the
                voltage array).

        Returns:
            Tuple[List[Allocation], List[Allocation]]:
                The list of allocations for the loads and the list of allocations for the generators (in the same
                order than in the input)
        """
        # A few basic checks
        assert len(load_voltages) == len(load_maximum_powers)
        assert len(generator_voltages) == len(generator_maximum_powers)

        # Manipulate numpy arrays
        load_voltages = np.array(load_voltages, dtype=np.float_)
        generator_voltages = np.array(generator_voltages, dtype=np.float_)

        # Compute the maximal violation error
        epsilon_error_load = (load_voltages - self.maximum_voltage).max()
        epsilon_error_generator = (generator_voltages - self.maximum_voltage).max()
        epsilon_error = max(epsilon_error_generator, epsilon_error_load)

        # Update the integral error
        self._lambda_error = max(self._lambda_error + epsilon_error * self.duration, 0)

        # Compute mu (hte p_max scale factor)
        mu = np.clip(a=1 - self.sigma * epsilon_error - self.tau * self._lambda_error, a_min=0, a_max=1)

        # Create the allocations objects
        # No control on the load ie. they consume what they want
        load_allocations = [Allocation(aid=next(self._count), p_value=p_max, q_value=None, duration=self.duration) for
                            p_max in load_maximum_powers]
        # We use the mu float to control the maximum production of the generators
        generator_allocations = [Allocation(aid=next(self._count), p_value=mu * p_max, q_value=None,
                                            duration=self.duration) for p_max in generator_maximum_powers]

        return load_allocations, generator_allocations
