import unittest

from entities.block import Block
from entities.container import DummyContainer
from tests.test_parameter_evaluation import make_container, make_parameter


class ParameterComplianceTests(unittest.TestCase):
    def test_active_criteria_and_fixed_weight_maximum(self):
        parameter = make_parameter(
            principal='LINE', principal_score='3',
            container_condition_score='99', container_grade_score='99',
            pol='', pod='B', route_score='2',
            vessel='ALL', voyage='', vessel_voyage_score='4',
            weight_range_score='1',
        )
        self.assertEqual(parameter.getMaxScore(), 10.0)
        self.assertEqual(parameter.compliance(make_container()), 0.9)
        self.assertEqual(parameter.compliance(make_container(weight='10')), 1.0)

    def test_and_and_zero_maximum(self):
        parameter = make_parameter(principal='LINE', and_score='10')
        self.assertEqual(parameter.getMaxScore(), 10.0)
        self.assertEqual(parameter.compliance(make_container()), 1.0)
        self.assertEqual(parameter.compliance(make_container(principal='OTHER')), 0.0)
        for parameter in (make_parameter(), make_parameter(and_score='0')):
            self.assertEqual(parameter.compliance(make_container()), 0.0)

    def test_maximum_is_calculated_only_at_initialization(self):
        parameter = make_parameter(principal='LINE', principal_score='3')
        parameter._calculateMaxScore = lambda: self.fail('Maximum recalculated')
        self.assertEqual(parameter.compliance(make_container()), 1.0)


class BlockComplianceTests(unittest.TestCase):
    def make_block(self):
        return Block('BR', 'B', 'B', '3', '1', '3', '0', '0')

    def test_best_ratio_and_average_count_forty_once_at_anchor(self):
        block = self.make_block()
        forty = make_container()
        for slot in (0, 1):
            block.getStack(0, slot).addContainer(forty, 0)
        block.getStack(0, 0).addParameter(make_parameter(and_score='10'))
        anchor = block.getStack(0, 1)
        anchor.addParameter(make_parameter(
            parameter_id='P1', principal='LINE', principal_score='6',
            container_fill='F', container_fill_score='4',
        ))
        anchor.addParameter(make_parameter(
            parameter_id='P2', principal='LINE', principal_score='4',
            container_fill='F', container_fill_score='1',
        ))
        block.getStack(0, 2).addContainer(
            make_container(container_id='C2', container_size='20'), 0,
        )
        self.assertAlmostEqual(block.parameterCompliance(), 0.4)

    def test_empty_dummy_and_floating_containers(self):
        block = self.make_block()
        self.assertEqual(block.parameterCompliance(), 0.0)
        stack = block.getStack(0, 0)
        stack.replaceContainer(DummyContainer(), 0)
        self.assertEqual(block.parameterCompliance(), 0.0)
        stack.addContainer(make_container(container_size='20'), 2)
        stack.addParameter(make_parameter(and_score='5'))
        self.assertEqual(block.parameterCompliance(), 1.0)


if __name__ == '__main__':
    unittest.main()
