# Copyright 2023 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

"""Tests for converters."""

import pyglove as pg
from vizier import pyvizier as vz
from vizier._src.pyglove import constants
from vizier._src.pyglove import converters
from absl.testing import absltest
from absl.testing import parameterized


class VizierCreatedSearchSpaceTest(parameterized.TestCase):
  """Tests for search space created from vz.SearchSpace."""

  def _search_space(self) -> vz.SearchSpace:
    ss = vz.SearchSpace()
    root = ss.root
    root.add_float_param('double', -1., 1.)
    root.add_int_param('int', 2, 4)
    root.add_discrete_param('discrete_int', (-2, 4, 7, 8))
    root.add_discrete_param('discrete_double', (-2.1, 4.1, 7.1, 8.1))
    root.add_categorical_param('categorical', ('a', 'b', 'c'))
    return ss

  def test_dna_spec(self):
    vc = converters.VizierConverter.from_problem(
        vz.ProblemStatement(self._search_space()))
    self.assertLen(vc.dna_spec, 5)
    self.assertNotEmpty(
        vc.problem.metadata.ns(constants.METADATA_NAMESPACE)[
            constants.STUDY_METADATA_KEY_DNA_SPEC])

  def test_dna_to_trial(self):
    vc = converters.VizierConverter.from_problem(
        vz.ProblemStatement(self._search_space()))
    self.assertDictEqual(
        vc.to_trial(vc.dna_spec.first_dna(),
                    fallback='raise_error').parameters.as_dict(), {
                        'double': -1,
                        'int': 2,
                        'discrete_int': -2,
                        'discrete_double': -2.1,
                        'categorical': 'a'
                    })

  @parameterized.parameters((7,), (7.,))
  def test_trial_to_dna(self, discrete_int_value):
    vc = converters.VizierConverter.from_problem(
        vz.ProblemStatement(search_space=self._search_space()))
    trial = vz.Trial()
    trial.parameters['double'] = -.5
    trial.parameters['int'] = 3
    trial.parameters['discrete_int'] = discrete_int_value
    trial.parameters['discrete_double'] = 4.1
    trial.parameters['categorical'] = 'a'
    self.assertEqual(vc.to_dna(trial), pg.DNA([-.5, 1, 2, 1, 0]))


class PyGloveCreatedSearchSpaceTest(parameterized.TestCase):
  """Tests for PyGlove created search space."""

  def _dna_spec(self) -> pg.DNASpec:

    class CustomTypeDecision(pg.hyper.CustomHyper):

      def custom_decode(self, dna):
        return dna.value

    search_space = pg.Dict(
        a=CustomTypeDecision(),
        b=pg.manyof(2, [0, 0, 2, 2]),
        x=pg.oneof([3, 2]),
        y=pg.floatv(0.1, 2.0),
        z=pg.oneof(['foo', 'bar']),
    )
    return pg.dna_spec(search_space)

  def test_search_space(self):
    vc = converters.VizierConverter.from_dna_spec(self._dna_spec())
    # Custom-type decision point `a` is not part of the search space.
    # But `b` has two decision points.
    self.assertLen(vc.search_space.parameters, 5)
    self.assertNotEmpty(
        vc.problem.metadata.ns(constants.METADATA_NAMESPACE)[
            constants.STUDY_METADATA_KEY_DNA_SPEC])

  def test_dna_to_trial(self):
    dna_spec = self._dna_spec()
    vc = converters.VizierConverter.from_dna_spec(dna_spec)
    dna = pg.DNA(['abc', [1, 2], 0, 0.5, 1], spec=dna_spec)
    trial = vc.to_trial(dna, fallback='raise_error')
    self.assertLen(trial.parameters, 5)
    self.assertEqual(trial.parameters['b[0]'], vz.ParameterValue('1/4 (0)'))
    self.assertEqual(trial.parameters['b[1]'], vz.ParameterValue('2/4 (2)'))
    self.assertEqual(trial.parameters['x'], vz.ParameterValue(3))
    self.assertEqual(trial.parameters['y'], vz.ParameterValue(0.5))
    self.assertEqual(trial.parameters['z'], vz.ParameterValue('1/2 (\'bar\')'))
    self.assertEqual(
        pg.from_json_str(
            trial.metadata.ns(constants.METADATA_NAMESPACE)
            [constants.TRIAL_METADATA_KEY_CUSTOM_TYPE_DECISIONS]), {'a': 'abc'})

  def test_trial_to_dna(self):
    vc = converters.VizierConverter.from_dna_spec(self._dna_spec())
    trial = vz.Trial()
    trial.parameters['x'] = 2.0
    trial.parameters['b[0]'] = '1/4 (0)'
    trial.parameters['b[1]'] = '2/4 (2)'
    trial.parameters['y'] = 0.5
    trial.parameters['z'] = '1/2 (\'bar\')'
    trial.metadata.ns(constants.METADATA_NAMESPACE)[
        constants.TRIAL_METADATA_KEY_CUSTOM_TYPE_DECISIONS] = pg.to_json_str(
            {'a': 'abc'})
    self.assertEqual(vc.to_dna(trial), pg.DNA(['abc', [1, 2], 1, 0.5, 1]))


class MakeParameterConfigTest(absltest.TestCase):
  """Tests for make parameter configs from DNASpec."""

  def testScale(self):
    """Test scale type conversion."""
    self.assertEqual(converters.get_scale_type(None), vz.ScaleType.LINEAR)
    self.assertEqual(converters.get_scale_type('linear'), vz.ScaleType.LINEAR)
    self.assertEqual(converters.get_scale_type('log'), vz.ScaleType.LOG)
    self.assertEqual(
        converters.get_scale_type('rlog'), vz.ScaleType.REVERSE_LOG)
    with self.assertRaisesRegex(
        ValueError, 'Unsupported scale type'):
      converters.get_scale_type('unknown')

  def testHyperValueAsRoot(self):
    """Test using hyper value as search space root."""
    search_space = pg.oneof([1, 2])
    actual = converters.VizierConverter.from_dna_spec(
        pg.dna_spec(search_space)).search_space
    expected = vz.SearchSpace()
    expected.root.add_discrete_param('$', [1, 2])
    self.assertEqual(actual, expected)

  def testFlatSearchSpace(self):
    """Test flat search spaces."""

    class CustomDecisionPoint(pg.geno.CustomDecisionPoint):

      def custom_decode(self, dna):
        return dna.value

    search_space = pg.Dict(
        # custom decision point 'a' will not be inserted as a part of
        # parameter config.
        a=CustomDecisionPoint(),
        b=pg.oneof([2, 1]),
        x=pg.oneof([2, 2, 1]),
        y=[pg.floatv(1e-6, 1.0, scale='log')],
        z=pg.Dict(p=pg.manyof(2, ['foo', 'bar'])),
    )
    actual = converters.VizierConverter.from_dna_spec(
        pg.dna_spec(search_space)).search_space
    expected = vz.SearchSpace()
    root = expected.root
    # Feasible points of discrete params are sorted.
    root.add_discrete_param('b', [1, 2])
    root.add_categorical_param('x', ['0/3 (2)', '1/3 (2)', '2/3 (1)'])
    root.add_float_param('y[0]', 1e-6, 1.0, scale_type=vz.ScaleType.LOG)
    root.add_categorical_param('z.p[0]', ['0/2 (\'foo\')', '1/2 (\'bar\')'])
    root.add_categorical_param('z.p[1]', ['0/2 (\'foo\')', '1/2 (\'bar\')'])

    self.assertEqual(actual, expected)

  def testHierarchicalSearchSpace(self):
    """Test hierarchical search space."""
    search_space = pg.oneof([[pg.oneof([1, 2])],
                             pg.Dict(x=pg.floatv(0.1, 0.5)),
                             pg.manyof(2,
                                       [pg.oneof(['foo', 'bar']), True, False])
                            ])
    actual = converters.VizierConverter.from_dna_spec(
        pg.dna_spec(search_space)).search_space

    expected = vz.SearchSpace()
    root = expected.root
    categories = [
        '0/3 ([0: OneOf(candidates=[0: 1, 1: 2])])',
        '1/3 ({x=Float(min_value=0.1, max_value=0.5)})',
        ('2/3 (ManyOf(num_choices=2, candidates=[0: OneOf('
         'candidates=[0: \'foo\', 1: \'bar\']), 1: True, 2: False]))')
    ]
    dollar = root.add_categorical_param('$', categories)
    dollar.select_values([categories[0]]).add_discrete_param(
        '[=0/3][0]',
        [
            1,
            2,
        ],
    )
    dollar.select_values([categories[1]]).add_float_param(
        name='[=1/3].x',
        min_value=0.1,
        max_value=0.5,
        scale_type=vz.ScaleType.LINEAR,
    )

    branch2 = dollar.select_values([categories[2]])

    def _add_children(name):
      branch2.add_categorical_param(
          name,
          [
              '0/3 (OneOf(candidates=[0: \'foo\', 1: \'bar\']))', '1/3 (True)',
              '2/3 (False)'
          ],
      ).select_values(['0/3 (OneOf(candidates=[0: \'foo\', 1: \'bar\']))'
                      ]).add_categorical_param(
                          f'{name}[=0/3]',
                          [
                              '0/2 (\'foo\')',
                              '1/2 (\'bar\')',
                          ],
                      )

    _add_children('[=2/3][0]')
    _add_children('[=2/3][1]')
    self.assertEqual(
        expected, actual, msg=f'expected={expected}, actual={actual}')


if __name__ == '__main__':
  absltest.main()
