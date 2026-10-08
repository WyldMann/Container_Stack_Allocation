"""Compare complete candidate searches against the original access algorithm.

Run from the repository root:
    python -m tests.benchmark_loader_access --sizes 10 20 30 --repeats 3

All stacks have a matching, positive-scoring parameter. Timings include context
preparation and do not rely on filtering candidates with missing parameters.
These are diagnostic timings, not machine-dependent unit-test thresholds.
"""

import argparse
import random
from statistics import median
from time import perf_counter
from types import SimpleNamespace

from entities.feasibility.placement_feasibility import PlacementFeasibility
from entities.yard import Yard
from tests.loader_access_reference import ReferencePlacementFeasibility


class BenchmarkParameter:
    def evaluate(self, container):
        return 1.0

    def __str__(self):
        return 'BENCHMARK'


def make_yard(side, scenario):
    yard = Yard([dict(
        BRANCH_ID='B', BLOCK_ID='A', BLOCK_CODE='A',
        SLOT_COUNT=str(side), ROW_COUNT=str(side), MAX_TIER='3',
        POS_X='0', POS_Y='0',
    )])
    parameter = BenchmarkParameter()
    yard.params[str(parameter)] = parameter
    block = yard.getBlockByID('A')
    rng = random.Random(2401)
    for row in range(side):
        for slot in range(side):
            block.getStack(row, slot).addParameter(parameter)
        # Paired columns share height/size so both container sizes have valid
        # opportunities. Full pairs make obstacles in the congested scenario.
        for slot in range(0, side, 2):
            sample = rng.random()
            count = 0
            if scenario == 'partial' and sample < 0.5:
                count = 1
            elif scenario == 'congested':
                count = 3 if sample < 0.65 else (1 if sample < 0.9 else 0)
            size = '40' if slot + 1 < side and rng.random() < 0.5 else '20'
            container = SimpleNamespace(getContSize=lambda size=size: size)
            for partner in range(slot, min(slot + 2, side)):
                for tier in range(count):
                    block.getStack(row, partner).addContainer(container, tier)
    return yard


def benchmark(side, scenario, size, repeats):
    yard = make_yard(side, scenario)
    container = SimpleNamespace(getContSize=lambda: size)
    reference = ReferencePlacementFeasibility()
    optimized = PlacementFeasibility()
    timings = {'reference': [], 'optimized': []}
    expected = None
    for repeat in range(repeats):
        methods = [('reference', reference), ('optimized', optimized)]
        # Alternate timing order to reduce systematic warm-up bias.
        if repeat % 2:
            methods.reverse()
        for name, evaluator in methods:
            yard.feasibility = evaluator
            start = perf_counter()
            result = yard.findCoordsCandidates(container)
            timings[name].append(perf_counter() - start)
            if expected is None:
                expected = result
            elif result != expected:
                raise AssertionError(f'Candidate results differ: {side=} {scenario=} {size=}')
    return len(expected[2]), median(timings['reference']), median(timings['optimized'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', type=int, nargs='+', default=[10, 20, 30])
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or any(side < 1 for side in args.sizes):
        parser.error('sizes and repeats must be positive')
    print('cells scenario   size candidates reference_s optimized_s speedup')
    for side in args.sizes:
        for scenario in ('empty', 'partial', 'congested'):
            for size in ('20', '40'):
                candidates, before, after = benchmark(side, scenario, size, args.repeats)
                print(f'{side * side:5} {scenario:10} {size:>4} {candidates:10} '
                      f'{before:11.6f} {after:11.6f} {before / after:7.2f}x', flush=True)


if __name__ == '__main__':
    main()
