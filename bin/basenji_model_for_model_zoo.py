#!/usr/bin/env python
import tensorflow as tf
import numpy as np


def basenji_model(input_shape, output_shape, augment_rc=True, augment_shift=3):
    """
    Basenji model turned into a single function.
    inputs (None, 131072, 4)
    """

    sequence = tf.keras.Input(shape=input_shape, name='sequence')
    # TODO:augmentation layer
    #StochasticReverseComplement
    if augment_rc:
      current, reverse_bool = StochasticReverseComplement()(sequence)
    #StochasticShift
    if augment_shift != [0]:
      current = StochasticShift(augment_shift)(current)
    #1st conv block
    #{'activation': 'gelu', 'batch_norm': True, 'bn_momentum': 0.9,
    #'filters': 64, 'kernel_size': 15, 'pool_size': 8}
    current = conv_block(current, filters=64, kernel_size=15, activation='gelu', activation_end=None,
        strides=1, dilation_rate=1, l2_scale=0, dropout=0, conv_type='standard', residual=False,
        pool_size=8, batch_norm=True, bn_momentum=0.9, bn_gamma=None, bn_type='standard',
        kernel_initializer='he_normal', padding='same')


    #conv_tower
    #{'activation': 'gelu', 'batch_norm': True, 'bn_momentum': 0.9,
    #'filters_init': 64, 'filters_mult': 1.125, 'kernel_size': 5,
    #'pool_size': 4, 'repeat': 2}
    current = conv_tower(current, filters_init=64, filters_mult=1.125, repeat=2,
        pool_size=4, kernel_size=5, batch_norm=True, bn_momentum=0.9,
        activation='gelu')


    #dilated residual
    #{'activation': 'gelu', 'batch_norm': True, 'bn_momentum': 0.9,
    #'filters': 32, 'rate_mult': 2, 'repeat': 6, 'dropout': 0.25}
    current = dilated_residual(current, filters=32, kernel_size=3, rate_mult=2,
        conv_type='standard', dropout=0.25, repeat=6, round=False,
        activation='gelu', batch_norm=True, bn_momentum=0.9)
    #conv_block
    #{'activation': 'gelu', 'batch_norm': True, 'bn_momentum': 0.9,
    #'filters': 64, 'dropout': 0.05}
    current = conv_block(current, filters=64, kernel_size=1, activation='gelu',
        dropout=0.05, batch_norm=True, bn_momentum=0.9)

    #dense
    #{'activation': 'softplus', 'batch_norm': True, 'bn_momentum': 0.9,
    #'units': X}
    current = dense(current, output_shape, activation='softplus',
        batch_norm=True, bn_momentum=0.9)

    # switch reverse
    outputs = SwitchReverse()([current, reverse_bool])

    model = tf.keras.Model(inputs=sequence, outputs=outputs)
    print(model.summary())
    return model


def activate(current, activation, verbose=False):
  if verbose: print('activate:',activation)
  if activation == 'relu':
    current = tf.keras.layers.ReLU()(current)
  elif activation == 'polyrelu':
    current = PolyReLU()(current)
  elif activation == 'gelu':
    current = GELU()(current)
  elif activation == 'sigmoid':
    current = tf.keras.layers.Activation('sigmoid')(current)
  elif activation == 'tanh':
    current = tf.keras.layers.Activation('tanh')(current)
  elif activation == 'exp':
    current = Exp()(current)
  elif activation == 'softplus':
    current = Softplus()(current)
  else:
    print('Unrecognized activation "%s"' % activation, file=sys.stderr)
    exit(1)

  return current


class GELU(tf.keras.layers.Layer):
  def __init__(self, **kwargs):
    super(GELU, self).__init__(**kwargs)
  def call(self, x):
    # return tf.keras.activations.sigmoid(1.702 * x) * x
    return tf.keras.activations.sigmoid(tf.constant(1.702) * x) * x


############################################################
# Convolution
############################################################
def conv_block(inputs, filters=None, kernel_size=1, activation='relu', activation_end=None,
    strides=1, dilation_rate=1, l2_scale=0, dropout=0, conv_type='standard', residual=False,
    pool_size=1, batch_norm=False, bn_momentum=0.99, bn_gamma=None, bn_type='standard',
    kernel_initializer='he_normal', padding='same'):
  """Construct a single convolution block.

  Args:
    inputs:        [batch_size, seq_length, features] input sequence
    filters:       Conv1D filters
    kernel_size:   Conv1D kernel_size
    activation:    relu/gelu/etc
    strides:       Conv1D strides
    dilation_rate: Conv1D dilation rate
    l2_scale:      L2 regularization weight.
    dropout:       Dropout rate probability
    conv_type:     Conv1D layer type
    residual:      Residual connection boolean
    pool_size:     Max pool width
    batch_norm:    Apply batch normalization
    bn_momentum:   BatchNorm momentum
    bn_gamma:      BatchNorm gamma (defaults according to residual)

  Returns:
    [batch_size, seq_length, features] output sequence
  """

  # flow through variable current
  current = inputs

  # choose convolution type
  if conv_type == 'separable':
    conv_layer = tf.keras.layers.SeparableConv1D
  else:
    conv_layer = tf.keras.layers.Conv1D

  if filters is None:
    filters = inputs.shape[-1]

  # activation
  current = activate(current, activation)

  # convolution
  current = conv_layer(
    filters=filters,
    kernel_size=kernel_size,
    strides=strides,
    padding='same',
    use_bias=False,
    dilation_rate=dilation_rate,
    kernel_initializer=kernel_initializer,
    kernel_regularizer=tf.keras.regularizers.l2(l2_scale))(current)

  # batch norm
  if batch_norm:
    if bn_gamma is None:
      bn_gamma = 'zeros' if residual else 'ones'
    if bn_type == 'sync':
      bn_layer = tf.keras.layers.experimental.SyncBatchNormalization
    else:
      bn_layer = tf.keras.layers.BatchNormalization
    current = bn_layer(
      momentum=bn_momentum,
      gamma_initializer=bn_gamma)(current)

  # dropout
  if dropout > 0:
    current = tf.keras.layers.Dropout(rate=dropout)(current)

  # residual add
  if residual:
    current = tf.keras.layers.Add()([inputs,current])

  # end activation
  if activation_end is not None:
    current = activate(current, activation_end)

  # Pool
  if pool_size > 1:
    current = tf.keras.layers.MaxPool1D(
      pool_size=pool_size,
      padding=padding)(current)

  return current


############################################################
# Towers
############################################################
def conv_tower(inputs, filters_init, filters_mult=1, repeat=1, **kwargs):
  """Construct a reducing convolution block.

  Args:
    inputs:        [batch_size, seq_length, features] input sequence
    filters_init:  Initial Conv1D filters
    filters_mult:  Multiplier for Conv1D filters
    repeat:        Conv block repetitions

  Returns:
    [batch_size, seq_length, features] output sequence
  """

  # flow through variable current
  current = inputs

  # initialize filters
  rep_filters = filters_init

  for ri in range(repeat):
    # convolution
    current = conv_block(current,
      filters=int(np.round(rep_filters)),
      **kwargs)

    # update filters
    rep_filters *= filters_mult

  return current


def dilated_residual(inputs, filters, kernel_size=3, rate_mult=2,
    conv_type='standard', dropout=0, repeat=1, round=False, **kwargs):
  """Construct a residual dilated convolution block.

  Args:

  Returns:
  """

  # flow through variable current
  current = inputs

  # initialize dilation rate
  dilation_rate = 1.0

  for ri in range(repeat):
    rep_input = current

    # dilate
    current = conv_block(current,
      filters=filters,
      kernel_size=kernel_size,
      dilation_rate=int(np.round(dilation_rate)),
      conv_type=conv_type,
      bn_gamma='ones',
      **kwargs)

    # return
    current = conv_block(current,
      filters=rep_input.shape[-1],
      dropout=dropout,
      bn_gamma='zeros',
      **kwargs)

    # residual add
    current = tf.keras.layers.Add()([rep_input,current])

    # update dilation rate
    dilation_rate *= rate_mult
    if round:
      dilation_rate = np.round(dilation_rate)

  return current


# depracated, poorly named
def dense(inputs, units, activation='linear', kernel_initializer='he_normal',
          l2_scale=0, l1_scale=0, **kwargs):

  # apply dense layer
  current = tf.keras.layers.Dense(
    units=units,
    use_bias=True,
    activation=activation,
    kernel_initializer=kernel_initializer,
    kernel_regularizer=tf.keras.regularizers.l1_l2(l1_scale, l2_scale)
    )(inputs)

  return current


class StochasticReverseComplement(tf.keras.layers.Layer):
  """Stochastically reverse complement a one hot encoded DNA sequence."""
  def __init__(self):
    super(StochasticReverseComplement, self).__init__()
  def call(self, seq_1hot, training=None):
    if training:
      rc_seq_1hot = tf.gather(seq_1hot, [3, 2, 1, 0], axis=-1)
      rc_seq_1hot = tf.reverse(rc_seq_1hot, axis=[1])
      reverse_bool = tf.random.uniform(shape=[]) > 0.5
      src_seq_1hot = tf.cond(reverse_bool, lambda: rc_seq_1hot, lambda: seq_1hot)
      return src_seq_1hot, reverse_bool
    else:
      return seq_1hot, tf.constant(False)


class StochasticShift(tf.keras.layers.Layer):
  """Stochastically shift a one hot encoded DNA sequence."""
  def __init__(self, shift_max=0, pad='uniform'):
    super(StochasticShift, self).__init__()
    self.shift_max = shift_max
    self.augment_shifts = tf.range(-self.shift_max, self.shift_max+1)
    self.pad = pad

  def call(self, seq_1hot, training=None):
    if training:
      shift_i = tf.random.uniform(shape=[], minval=0, dtype=tf.int64,
                                  maxval=len(self.augment_shifts))
      shift = tf.gather(self.augment_shifts, shift_i)
      sseq_1hot = tf.cond(tf.not_equal(shift, 0),
                          lambda: shift_sequence(seq_1hot, shift),
                          lambda: seq_1hot)
      return sseq_1hot
    else:
      return seq_1hot

  def get_config(self):
    config = super().get_config().copy()
    config.update({
      'shift_max': self.shift_max,
      'pad': self.pad
    })
    return config

class SwitchReverse(tf.keras.layers.Layer):
  """Reverse predictions if the inputs were reverse complemented."""
  def __init__(self):
    super(SwitchReverse, self).__init__()
  def call(self, x_reverse):
    x = x_reverse[0]
    reverse = x_reverse[1]

    xd = len(x.shape)
    if xd == 3:
      rev_axes = [1]
    elif xd == 4:
      rev_axes = [1,2]
    else:
      raise ValueError('Cannot recognize SwitchReverse input dimensions %d.' % xd)

    return tf.keras.backend.switch(reverse,
                                   tf.reverse(x, axis=rev_axes),
                                   x)


def shift_sequence(seq, shift, pad_value=0.25):
  """Shift a sequence left or right by shift_amount.

  Args:
  seq: [batch_size, seq_length, seq_depth] sequence
  shift: signed shift value (tf.int32 or int)
  pad_value: value to fill the padding (primitive or scalar tf.Tensor)
  """
  if seq.shape.ndims != 3:
      print(seq.shape.ndims)
      raise ValueError('input sequence should be rank 3')
  input_shape = seq.shape

  pad = pad_value * tf.ones_like(seq[:, 0:tf.abs(shift), :])

  def _shift_right(_seq):
    # shift is positive
    sliced_seq = _seq[:, :-shift:, :]
    return tf.concat([pad, sliced_seq], axis=1)

  def _shift_left(_seq):
    # shift is negative
    sliced_seq = _seq[:, -shift:, :]
    return tf.concat([sliced_seq, pad], axis=1)

  sseq = tf.cond(tf.greater(shift, 0),
                 lambda: _shift_right(seq),
                 lambda: _shift_left(seq))
  sseq.set_shape(input_shape)

  return sseq
