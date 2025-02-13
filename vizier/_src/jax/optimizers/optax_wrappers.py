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

"""High-level wrappers for stochastic process hyperparameter optimizers."""

# TODO: Add optimizers that are frequently used in the literature.

from typing import Optional
from absl import logging
import attr
import chex
import jax
from jax import numpy as jnp
from jax import random
import optax
from tensorflow_probability.substrates import jax as tfp
from vizier._src.jax import stochastic_process_model as sp
from vizier._src.jax.optimizers import core

tfb = tfp.bijectors

OptState = chex.ArrayTree


@attr.define
class OptaxTrainWithRandomRestarts(core.Optimizer[core.Params]):
  """Wraps an Optax optimizer.

  It's recommended to use this optimizer with a loss function that normalizes by
  the number of observations. The unnormalized loss function for parameters `p`
  is typically of the form

  ```None
  -gp_likelihood(observations | p) + regularization(p)
  ```

  where regularization may be a negative prior log probability. The likelihood
  term is approximately proportional to the number of observations. As the
  number of observations changes over the course of a study, dividing the loss
  by this number helps ensure that loss values are roughly of the same order of
  magnitude, such that a constant learning rate may be used for gradient-based
  optimizers. Vizier library models make this adjustment automatically.

  Attributes:
    optimizer: Optax optimizer such as `optax.adam(1e-2)`.
    epochs: Number of train epochs.
    verbose: If >=1, logs the train progress. If >=2, logs the gradients.
    random_restarts: Must be positive; number of random initializations for the
      optimization.
    best_n: Number of best values to return from the initializations; must be
      less than or equal to `random_restarts`.
  """

  optimizer: optax.GradientTransformation = attr.field()
  epochs: int = attr.field(kw_only=True)
  verbose: int = attr.field(kw_only=True, default=0, converter=int)
  random_restarts: int = attr.field(kw_only=True, default=32)
  best_n: int = attr.field(kw_only=True, default=None)

  def __attrs_post_init__(self):
    if self.random_restarts < (self.best_n or 1):
      raise ValueError(
          f'Cannot generate {self.best_n} results from'
          f' {self.random_restarts} restarts'
      )
    if self.best_n is None:
      self.best_n = 0

  # TODO: Prevent retracing.
  def __call__(
      self,
      setup: core.Setup[core.Params],
      loss_fn: core.LossFunction[core.Params],
      rng: jax.random.KeyArray,
      *,
      constraints: Optional[sp.Constraint] = None,
      best_n: Optional[int] = None,
  ) -> tuple[core.Params, chex.ArrayTree]:
    if constraints is None or constraints.bijector is None:
      bijector = None
      unconstrained_loss_fn = loss_fn
    else:
      bijector = constraints.bijector
      unconstrained_loss_fn = lambda x: loss_fn(bijector(x))

    grad_fn = jax.value_and_grad(unconstrained_loss_fn, has_aux=True)

    def _setup_all(rng: jax.random.KeyArray) -> tuple[core.Params, OptState]:
      """Sets up both model params and optimizer state."""
      params = setup(rng)
      if bijector is not None:
        params = bijector.inverse(params)
      opt_state = self.optimizer.init(params)
      return params, opt_state

    def _train_step(
        params: core.Params, opt_state: OptState
    ) -> tuple[core.Params, OptState, chex.ArrayTree]:
      """One train step."""
      (loss, metrics), grads = grad_fn(params)
      logging.log_if(logging.INFO, 'gradients: %s', self.verbose >= 2, grads)
      updates, opt_state = self.optimizer.update(grads, opt_state, params)
      params = optax.apply_updates(params, updates)
      metrics['loss'] = loss
      return params, opt_state, metrics

    if self.random_restarts > 1:
      # Random restarts are implemented via jax.vmap.
      # Note that both setup_all and train_step are vmapped.
      rngs = random.split(rng, self.random_restarts)
      params, opt_state = jax.vmap(_setup_all)(rngs)
      train_step = jax.vmap(_train_step)
    else:
      params, opt_state = _setup_all(rng)
      train_step = _train_step

    logging.info('Initialized parameters. %s',
                 jax.tree_map(lambda x: x.shape, params))

    # See https://jax.readthedocs.io/en/latest/faq.html#buffer-donation.
    train_step = jax.jit(train_step, donate_argnums=[0, 1])
    metrics = []
    for epoch in range(self.epochs):
      params, opt_state, step_metrics = train_step(params, opt_state)
      logging.log_if(
          logging.INFO,
          'Epoch %s: metrics: %s',
          self.verbose >= 1,
          epoch,
          step_metrics,
      )
      metrics.append(step_metrics)

    # Convert `metrics` from a list of dicts to a dict of arrays with leftmost
    # dimension corresponding to train steps.
    outer_treedef = jax.tree_util.tree_structure([0] * self.epochs)
    transposed_metrics = jax.tree_util.tree_transpose(
        outer_treedef, jax.tree_util.tree_structure(step_metrics), metrics
    )
    metrics = jax.tree_util.tree_map(
        jnp.array,
        transposed_metrics,
        is_leaf=lambda x: jax.tree_util.tree_structure(x) == outer_treedef,
    )

    final_losses = metrics['loss'][-1]
    logging.info('Final loss: %s', final_losses)
    best_params = core.get_best_params(final_losses, params, best_n=best_n)
    if bijector is not None:
      best_params = bijector(best_params)
    return (best_params, metrics)
