#!/usr/bin/env python
from optparse import OptionParser
import os
import shutil
import sys
import time
import dataset
import basenji_model_for_model_zoo as model_zoo
import numpy as np
import json
import metrics
import tensorflow as tf
if tf.__version__[0] == '1':
  tf.compat.v1.enable_eager_execution()

# "train_epochs": 20,
# "clipnorm": 2

def main():
    usage = 'usage: %prog [options] <data_dir> <model_name> <output_dir> <params_file>...'
    parser = OptionParser(usage)
    parser.add_option('-b', dest='batch_size',
        default=4,
        help='Batch size for the model training [Default: %default]')
    parser.add_option('-p', dest='patience',
        default=8,
        help='Training patience [Default: %default]')
    parser.add_option('-l', dest='learning_rate',
        default=0.1,
        help='Learning rate [Default: %default]')
    parser.add_option('-m', dest='momentum',
        default=0.99,
        help='SGD momentum [Default: %default]')
    parser.add_option('-e', dest='n_epochs',
        default=8,
        help='Training patience [Default: %default]')
    parser.add_option('--clip_norm', dest='clip_norm',
        default=1000000,
        help='Training patience [Default: %default]')
    (options, args) = parser.parse_args()
    ########TODO:ADD THE REST OF THE parameters
    if len(args) < 4:
        parser.error('Must provide data_dir, model and output directory.')
    else:
        data_dir = args[0]
        model_name = args[1]
        output_dir = args[2]
        params_file = args[3]

    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
    ####LOAD DATA
  # read model parameters
    with open(params_file) as params_open:
        params = json.load(params_open)
    params_model = params['model']
    params_train = params['train']

    # read datasets
    train_data = []
    eval_data = []


    # load train data
    train_data.append(dataset.SeqDataset(data_dir,
    split_label='train',
    batch_size=params_train['batch_size'],
    mode='train'))

    # load eval data
    eval_data.append(dataset.SeqDataset(data_dir,
    split_label='valid',
    batch_size=params_train['batch_size'],
    mode='eval'))
    ##########################################



    # train, valid = load_data(data_dir, options.batch_size)
    # print(type(valid[0]))
    # print(len(valid))
    # print(valid)
    if model_name=='basenji':
        model = model_zoo.basenji_model((131072,4), 3)
    loss_fn = tf.keras.losses.Poisson(reduction=tf.keras.losses.Reduction.NONE)
    early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_pearsonr', #'val_aupr',#
                                                patience=options.patience,
                                                verbose=1,
                                                mode='max')
    # early_stop = EarlyStoppingMin(monitor='val_pearsonr', mode='max', verbose=1,
    #                patience=options.patience, min_epoch=1)
    save_best = tf.keras.callbacks.ModelCheckpoint('{}/model_best.h5'.format(output_dir),
                                                 save_best_only=True, mode='max',
                                                 monitor='val_pearsonr', verbose=1)
    callbacks = [
      early_stop,
      tf.keras.callbacks.TensorBoard(output_dir),
      tf.keras.callbacks.ModelCheckpoint('%s/model_check.h5'%output_dir),
      save_best]
    # fit model
    num_targets = model.output_shape[-1]
    print('num_targets ', num_targets)
    model_metrics = [metrics.PearsonR(num_targets), metrics.R2(num_targets)]

    optimizer = tf.keras.optimizers.SGD(
      learning_rate=options.learning_rate,
      momentum=options.momentum,
      clipnorm=options.clip_norm)

    model.compile(loss=loss_fn,
                optimizer=optimizer,
                metrics=model_metrics)
    model.fit(
      train,
      epochs=options.n_epochs,
      callbacks=callbacks,
      validation_data=valid)

# def load_data(data_dir, batch_size):
#
#     # read datasets
#     train_data = []
#     valid_data = []
#
#
#     # load train data
#     train_data.append(dataset.SeqDataset(data_dir,
#         split_label='train',
#         batch_size=batch_size,
#         mode='train'))
#
#     # load eval data
#     valid_data.append(dataset.SeqDataset(data_dir,
#         split_label='valid',
#         batch_size=batch_size,
#         mode='eval'))
#     return(train_data, valid_data)

################################################################################
# __main__
################################################################################
if __name__ == '__main__':
    main()
