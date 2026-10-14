import unittest

from entities import Container, Parameter


def make_parameter(**overrides):
    fields = dict(
        parameter_id='P', parameter_name='Test',
        principal='', principal_score='',
        container_condition='', container_condition_score='',
        container_fill='', container_fill_score='',
        container_size='', container_size_score='',
        container_grade='', container_grade_score='',
        pol='', pod='', route_score='',
        vessel='', voyage='', vessel_voyage_score='',
        weight_start='', weight_end='', weight_range_score='',
    )
    return Parameter(**(fields | overrides))


def make_container(**overrides):
    fields = dict(
        container_id='C', principal='LINE', container_condition='OK', container_fill='E',
        container_size='40', container_grade='PG', pol='A', pod='B',
        vessel='SHIP', voyage='1', weight='', move_time='',
    )
    return Container(**(fields | overrides))


class ParameterEvaluationTests(unittest.TestCase):
    def test_operation_type_defaults_preserve_existing_parameters(self):
        parameter = make_parameter()
        self.assertEqual(parameter.getOpType(), '')
        self.assertEqual(parameter.getOpTypeScore(), 0)

    def test_operation_type_matching_in_additive_and_and_modes(self):
        for expected, score, actual, additive, and_result in (
            ('D', '5', 'D', 8, 10),
            ('D', '5', 'L', 3, 0),
            ('D', '5', '', 3, 0),
            ('', '5', 'L', 3, 10),
            ('ALL', '5', 'L', 8, 10),
            ('ALL', '5', '', 8, 10),
            ('D', '0', 'D', 3, 10),
            ('D', '0', 'L', 3, 0),
            ('D', '', 'D', 3, 10),
            ('D', '', 'L', 3, 0),
        ):
            with self.subTest(expected=expected, score=score, actual=actual):
                parameter = make_parameter(
                    principal='LINE', principal_score='3',
                    operation_type=expected, operation_type_score=score,
                )
                container = make_container(operation_type=actual)
                self.assertEqual(parameter.evaluate(container), additive)
                parameter.and_score = 10
                self.assertEqual(parameter.evaluate(container), and_result)

    def test_partial_match_adds_points_but_fails_and(self):
        parameter = make_parameter(
            principal='LINE', principal_score='3',
            container_condition='DM', container_condition_score='5',
            container_fill='E', container_fill_score='2',
            container_size='40', container_size_score='4', and_score='20',
        )
        container = make_container()
        self.assertEqual(parameter.evaluateAdd(container), 9)
        self.assertEqual(parameter.evaluate(container), 0)
        self.assertEqual(parameter.evaluate(make_container(container_condition='DM')), 20)

    def test_blank_grade_is_ignored_even_when_container_grade_is_blank(self):
        for grade in ('', 'PG'):
            with self.subTest(grade=grade):
                parameter = make_parameter(container_grade_score='5', and_score='10')
                container = make_container(container_grade=grade)
                self.assertEqual(parameter.evaluateAdd(container), 0)
                self.assertEqual(parameter.evaluate(container), 10)

    def test_grade_membership_and_wildcard(self):
        for expected, actual, matches in (
            ('PG,FG', 'FG', True),
            ('PG,FG', 'GG', False),
            ('ALL', '', True),
        ):
            with self.subTest(expected=expected, actual=actual):
                parameter = make_parameter(
                    container_grade=expected, container_grade_score='5', and_score='10',
                )
                container = make_container(container_grade=actual)
                self.assertEqual(parameter.evaluateAdd(container), 5 if matches else 0)
                self.assertEqual(parameter.evaluate(container), 10 if matches else 0)

    def test_grouped_criteria_require_both_components_and_award_once(self):
        parameter = make_parameter(
            pol='A', pod='B', route_score='3',
            vessel='SHIP', voyage='1', vessel_voyage_score='7', and_score='20',
        )
        for overrides, additive, and_result in (
            ({}, 10, 20),
            ({'pol': 'X'}, 7, 0),
            ({'pod': 'X'}, 7, 0),
            ({'vessel': 'X'}, 3, 0),
            ({'voyage': 'X'}, 3, 0),
        ):
            with self.subTest(overrides=overrides):
                container = make_container(**overrides)
                self.assertEqual(parameter.evaluateAdd(container), additive)
                self.assertEqual(parameter.evaluate(container), and_result)

    def test_blank_and_wildcard_text_components(self):
        parameter = make_parameter(
            principal='ALL', principal_score='2',
            pol='', pod='B', route_score='3',
            vessel='ALL', voyage='', vessel_voyage_score='7', and_score='20',
        )
        container = make_container(principal='', pol='X', vessel='', voyage='9')
        self.assertEqual(parameter.evaluateAdd(container), 12)
        self.assertEqual(parameter.evaluate(container), 20)

    def test_zero_score_criterion_still_constrains_and(self):
        parameter = make_parameter(principal='OTHER', and_score='10')
        self.assertEqual(parameter.evaluate(make_container()), 0)
        self.assertEqual(parameter.evaluate(make_container(principal='OTHER')), 10)

    def test_weight_bounds_are_inclusive_and_missing_weight_is_skipped(self):
        parameter = make_parameter(
            weight_start='10', weight_end='20', weight_range_score='4', and_score='10',
        )
        for weight, additive, and_result in (
            ('9', 0, 0), ('10', 4, 10), ('15', 4, 10),
            ('20', 4, 10), ('21', 0, 0), ('', 0, 10),
        ):
            with self.subTest(weight=weight):
                container = make_container(weight=weight)
                self.assertEqual(parameter.evaluateAdd(container), additive)
                self.assertEqual(parameter.evaluate(container), and_result)

    def test_no_active_criteria_and_mode_selection(self):
        container = make_container()
        self.assertEqual(make_parameter().evaluate(container), 0)
        self.assertEqual(make_parameter(and_score='10').evaluate(container), 10)
        self.assertEqual(make_parameter().evaluateAnd(container), 0)
        fields = dict(principal='LINE', principal_score='3')
        self.assertEqual(make_parameter(**fields).evaluate(container), 3)
        self.assertEqual(make_parameter(**fields, and_score='0').evaluate(container), 0)

    def test_additive_zero_total_guard_is_preserved(self):
        parameter = make_parameter(
            principal='LINE', principal_score='3',
            container_fill='F', container_fill_score='-3',
        )
        self.assertEqual(parameter.evaluate(make_container()), 0)


if __name__ == '__main__':
    unittest.main()
