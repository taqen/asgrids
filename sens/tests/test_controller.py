#!/usr/bin/env python
# -*- coding: utf-8 -*-

import numpy as np

from ..controller import PIController
from ..defs import Allocation


def test_pi_controller():
    # Create the constants
    duration = 10  # seconds
    generator_maximum_powers = 5000 * np.array([1, 2, 3], dtype=np.float_)  # W
    load_maximum_powers = 5000 * np.array([2, 4], dtype=np.float_)  # W
    nb_time_steps = 100
    nb_loads = len(load_maximum_powers)
    nb_generators = len(generator_maximum_powers)

    #
    # First example: no over-voltages (so no reduction of production)
    #
    pi_controller = PIController(maximum_voltage=250, sigma=5e-2, tau=4e-5, duration=duration)
    aid_emitted = set()
    base_voltages = np.exp(-(np.arange(nb_time_steps, dtype=np.float_) - 50) ** 2 / 12 ** 2)
    load_voltages = np.vstack((240 * base_voltages, 245 * base_voltages)).T
    generator_voltages = np.vstack((230 * base_voltages, 245 * base_voltages, 240 * base_voltages)).T

    for t in range(nb_time_steps):
        la, ga = pi_controller.generate_allocations(load_voltages=load_voltages[t, :],
                                                    generator_voltages=generator_voltages[t, :],
                                                    generator_maximum_powers=generator_maximum_powers,
                                                    load_maximum_powers=load_maximum_powers)

        assert len(la) == nb_loads
        assert len(ga) == nb_generators
        for i, a in enumerate(la):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            assert a.p_value == load_maximum_powers[i]  # never curtail loads

        for i, a in enumerate(ga):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            assert a.p_value == generator_maximum_powers[i]  # no over-voltage at all in the network so no curtailment

    #
    # Second example: over-voltage for a single generator
    #
    pi_controller = PIController(maximum_voltage=250, sigma=5e-2, tau=4e-5, duration=duration)
    aid_emitted = set()
    base_voltages = np.exp(-(np.arange(nb_time_steps, dtype=np.float_) - 50) ** 2 / 12 ** 2)
    load_voltages = np.vstack((240 * base_voltages, 245 * base_voltages)).T
    generator_voltages = np.vstack((230 * base_voltages, 245 * base_voltages, 255 * base_voltages)).T

    for t in range(nb_time_steps):
        la, ga = pi_controller.generate_allocations(load_voltages=load_voltages[t, :],
                                                    generator_voltages=generator_voltages[t, :],
                                                    generator_maximum_powers=generator_maximum_powers,
                                                    load_maximum_powers=load_maximum_powers)

        assert len(la) == nb_loads
        assert len(ga) == nb_generators
        for i, a in enumerate(la):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            assert a.p_value == load_maximum_powers[i]  # never curtail loads

        percent_curtailed = None
        for i, a in enumerate(ga):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            if (generator_voltages[t, :] > 250).any():
                # over-voltages so curtailment of *all* producers
                assert a.p_value < generator_maximum_powers[i]

                # The same percentages applied on all producers
                if percent_curtailed is None:
                    percent_curtailed = a.p_value / generator_maximum_powers[i]
                else:
                    assert np.isclose(percent_curtailed, a.p_value / generator_maximum_powers[i])
            else:
                assert a.p_value == generator_maximum_powers[i]  # no over-voltage in the network so no curtailment

    #
    # Third example: over-voltage for a single load
    #
    pi_controller = PIController(maximum_voltage=250, sigma=5e-2, tau=4e-5, duration=duration)
    aid_emitted = set()
    base_voltages = np.exp(-(np.arange(nb_time_steps, dtype=np.float_) - 50) ** 2 / 12 ** 2)
    load_voltages = np.vstack((240 * base_voltages, 260 * base_voltages)).T
    generator_voltages = np.vstack((230 * base_voltages, 245 * base_voltages, 245 * base_voltages)).T

    for t in range(nb_time_steps):
        la, ga = pi_controller.generate_allocations(load_voltages=load_voltages[t, :],
                                                    generator_voltages=generator_voltages[t, :],
                                                    generator_maximum_powers=generator_maximum_powers,
                                                    load_maximum_powers=load_maximum_powers)

        assert len(la) == nb_loads
        assert len(ga) == nb_generators
        for i, a in enumerate(la):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            assert a.p_value == load_maximum_powers[i]  # never curtail loads

        percent_curtailed = None
        for i, a in enumerate(ga):
            assert isinstance(a, Allocation)
            assert a.aid not in aid_emitted
            aid_emitted.add(a.aid)
            assert a.q_value is None
            assert a.duration == duration
            if (load_voltages[t, :] > 250).any():
                # over-voltages so curtailment of *all* producers
                assert a.p_value < generator_maximum_powers[i]

                # The same percentages applied on all producers
                if percent_curtailed is None:
                    percent_curtailed = a.p_value / generator_maximum_powers[i]
                else:
                    assert np.isclose(percent_curtailed, a.p_value / generator_maximum_powers[i])
            else:
                assert a.p_value == generator_maximum_powers[i]  # no over-voltage in the network so no curtailment
