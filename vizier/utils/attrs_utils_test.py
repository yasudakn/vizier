"""Tests for attrs_utils."""

from typing import Any

import attrs
import numpy as np

from vizier.utils import attrs_utils
from absl.testing import absltest
from absl.testing import parameterized


class ValidatorsTest(parameterized.TestCase):

  @parameterized.parameters(
      (attrs_utils.assert_not_empty, [], False),
      (attrs_utils.assert_not_empty, [1], True),
      (attrs_utils.assert_not_negative, 0, -1),
      (attrs_utils.assert_not_negative, 0, True),
      (attrs_utils.assert_not_negative, 1, True),
      (attrs_utils.assert_not_none, None, False),
      (attrs_utils.assert_not_none, 0, True),
  )
  def test_validator(self, validator, value: Any, result: bool):

    @attrs.define
    class Test:
      x = attrs.field(validator=validator)

    if result:
      Test(value)
    else:
      with self.assertRaises(ValueError):
        Test(value)

  def test_good_shape_none(self):
    _ShapeEqualsTestAttr(np.zeros([3, 5]), None)
    _ShapeEqualsTestAttr(np.zeros([3, 0]), None)

  def test_bad_shape(self):
    with self.assertRaises(ValueError):
      _ShapeEqualsTestAttr(np.zeros([3, 2]), 4)


@attrs.define
class _ShapeEqualsTestAttr:
  x = attrs.field(validator=attrs_utils.shape_equals(lambda v: (3, v.d)))
  d = attrs.field()


class ShapeEqualsTest(absltest.TestCase):

  def test_good_shape(self):
    _ShapeEqualsTestAttr(np.zeros([3, 2]), 2)

  def test_good_shape_none(self):
    _ShapeEqualsTestAttr(np.zeros([3, 5]), None)
    _ShapeEqualsTestAttr(np.zeros([3, 0]), None)

  def test_bad_shape(self):
    with self.assertRaises(ValueError):
      _ShapeEqualsTestAttr(np.zeros([3, 2]), 4)


if __name__ == '__main__':
  absltest.main()
