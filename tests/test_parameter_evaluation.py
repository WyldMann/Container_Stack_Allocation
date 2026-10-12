import unittest

from entities import Container, Parameter


def make_parameter(**overrides):
    fields = dict(
        PARAM_ID='P', PARAM_NAME='Test',
        PRINCIPAL='', PRINCIPAL_SCORE='',
        CONT_CONDITION='', CONT_CONDITION_SCORE='',
        CONT_FILL='', CONT_FILL_SCORE='',
        CONT_SIZE='', CONT_SIZE_SCORE='',
        CONT_GRADE='', CONT_GRADE_SCORE='',
        POL='', POD='', ROUTE_SCORE='',
        VESSEL='', VOYAGE='', VESSEL_VOYAGE_SCORE='',
        WEIGHT_START='', WEIGHT_END='', WEIGHT_RANGE_SCORE='',
    )
    return Parameter(**(fields | overrides))


def make_container(**overrides):
    fields = dict(
        CONTNO='C', PRINCIPAL='LINE', DMG_FLAG='OK', FULLMT='E',
        CONTSIZE='40', CONT_GRADE='PG', POL='A', POD='B',
        VESSEL='SHIP', VOYAGE='1', WEIGHT='', MOVE_TIME='',
    )
    return Container(**(fields | overrides))


class ParameterEvaluationTests(unittest.TestCase):
    def test_partial_match_adds_points_but_fails_and(self):
        parameter = make_parameter(
            PRINCIPAL='LINE', PRINCIPAL_SCORE='3',
            CONT_CONDITION='DM', CONT_CONDITION_SCORE='5',
            CONT_FILL='E', CONT_FILL_SCORE='2',
            CONT_SIZE='40', CONT_SIZE_SCORE='4', AND_SCORE='20',
        )
        container = make_container()
        self.assertEqual(parameter.evaluateAdd(container), 9)
        self.assertEqual(parameter.evaluate(container), 0)
        self.assertEqual(parameter.evaluate(make_container(DMG_FLAG='DM')), 20)

    def test_blank_grade_is_ignored_even_when_container_grade_is_blank(self):
        for grade in ('', 'PG'):
            with self.subTest(grade=grade):
                parameter = make_parameter(CONT_GRADE_SCORE='5', AND_SCORE='10')
                container = make_container(CONT_GRADE=grade)
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
                    CONT_GRADE=expected, CONT_GRADE_SCORE='5', AND_SCORE='10',
                )
                container = make_container(CONT_GRADE=actual)
                self.assertEqual(parameter.evaluateAdd(container), 5 if matches else 0)
                self.assertEqual(parameter.evaluate(container), 10 if matches else 0)

    def test_grouped_criteria_require_both_components_and_award_once(self):
        parameter = make_parameter(
            POL='A', POD='B', ROUTE_SCORE='3',
            VESSEL='SHIP', VOYAGE='1', VESSEL_VOYAGE_SCORE='7', AND_SCORE='20',
        )
        for overrides, additive, and_result in (
            ({}, 10, 20),
            ({'POL': 'X'}, 7, 0),
            ({'POD': 'X'}, 7, 0),
            ({'VESSEL': 'X'}, 3, 0),
            ({'VOYAGE': 'X'}, 3, 0),
        ):
            with self.subTest(overrides=overrides):
                container = make_container(**overrides)
                self.assertEqual(parameter.evaluateAdd(container), additive)
                self.assertEqual(parameter.evaluate(container), and_result)

    def test_blank_and_wildcard_text_components(self):
        parameter = make_parameter(
            PRINCIPAL='ALL', PRINCIPAL_SCORE='2',
            POL='', POD='B', ROUTE_SCORE='3',
            VESSEL='ALL', VOYAGE='', VESSEL_VOYAGE_SCORE='7', AND_SCORE='20',
        )
        container = make_container(PRINCIPAL='', POL='X', VESSEL='', VOYAGE='9')
        self.assertEqual(parameter.evaluateAdd(container), 12)
        self.assertEqual(parameter.evaluate(container), 20)

    def test_zero_score_criterion_still_constrains_and(self):
        parameter = make_parameter(PRINCIPAL='OTHER', AND_SCORE='10')
        self.assertEqual(parameter.evaluate(make_container()), 0)
        self.assertEqual(parameter.evaluate(make_container(PRINCIPAL='OTHER')), 10)

    def test_weight_bounds_are_inclusive_and_missing_weight_is_skipped(self):
        parameter = make_parameter(
            WEIGHT_START='10', WEIGHT_END='20', WEIGHT_RANGE_SCORE='4', AND_SCORE='10',
        )
        for weight, additive, and_result in (
            ('9', 0, 0), ('10', 4, 10), ('15', 4, 10),
            ('20', 4, 10), ('21', 0, 0), ('', 0, 10),
        ):
            with self.subTest(weight=weight):
                container = make_container(WEIGHT=weight)
                self.assertEqual(parameter.evaluateAdd(container), additive)
                self.assertEqual(parameter.evaluate(container), and_result)

    def test_no_active_criteria_and_mode_selection(self):
        container = make_container()
        self.assertEqual(make_parameter().evaluate(container), 0)
        self.assertEqual(make_parameter(AND_SCORE='10').evaluate(container), 10)
        self.assertEqual(make_parameter().evaluateAnd(container), 0)
        fields = dict(PRINCIPAL='LINE', PRINCIPAL_SCORE='3')
        self.assertEqual(make_parameter(**fields).evaluate(container), 3)
        self.assertEqual(make_parameter(**fields, AND_SCORE='0').evaluate(container), 0)

    def test_additive_zero_total_guard_is_preserved(self):
        parameter = make_parameter(
            PRINCIPAL='LINE', PRINCIPAL_SCORE='3',
            CONT_FILL='F', CONT_FILL_SCORE='-3',
        )
        self.assertEqual(parameter.evaluate(make_container()), 0)


if __name__ == '__main__':
    unittest.main()
