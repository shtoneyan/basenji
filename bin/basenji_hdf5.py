#!/usr/bin/env python
from optparse import OptionParser
from collections import OrderedDict
import joblib
import multiprocessing
import random
import sys

import h5py
import numpy as np
import pyBigWig
import pysam
import tensorflow as tf

import basenji

'''
basenji_hdf5.py

Tile the genome and project the full functional profile to latent space
using a given model. Save the result in HDF5 for Basenji learning.

To Do:
 -If unmappable regions are cutting my data, I could squeeze a little more out
   by allowing them to sit at the edges of sequences where I'm not making
   predictions anyway.
'''

################################################################################
def main():
    usage = 'usage: %prog [options] <fasta_file> <sample_wigs_file> <hdf5_file>'
    parser = OptionParser(usage)
    parser.add_option('-f', dest='fourier_dim', default=None, type='int', help='Fourier transform dimension [Default: %default]')
    parser.add_option('-g', dest='gaps_file', help='Genome assembly gaps BED [Default: %default]')
    parser.add_option('-l', dest='seq_length', default=1024, type='int', help='Sequence length [Default: %default]')
    parser.add_option('-m', dest='params_file', help='Dimension reduction hyper-parameters file')
    parser.add_option('-s', dest='scent_file', help='Dimension reduction model file')
    parser.add_option('-p', dest='processes', default=1, type='int', help='Number parallel processes to load data [Default: %default]')
    parser.add_option('-t', dest='test_pct', type='float', default=0.01, help='Proportion of the data for testing [Default: %default]')
    parser.add_option('-v', dest='valid_pct', type='float', default=0.02, help='Proportion of the data for validation [Default: %default]')
    (options,args) = parser.parse_args()

    if len(args) != 3:
        parser.error('Must provide genome file, sample Wig/BigWig labels and paths, and model output file')
    else:
        fasta_file = args[0]
        sample_wigs_file = args[1]
        hdf5_file = args[2]

    ################################################################
    # assess bigwigs
    ################################################################
    # get wig files and labels
    target_wigs = OrderedDict()
    for line in open(sample_wigs_file):
        a = line.split()
        target_wigs[a[0]] = a[1]

    if options.fourier_dim is not None and 2*options.fourier_dim >= options.seq_length:
        print("Fourier transform to %d dims won't compress %d length sequences" % (options.fourier_dim, options.seq_length), file=sys.stderr)
        exit(1)


    ################################################################
    # prepare genomic segments
    ################################################################
    chrom_segments = basenji.genome.load_chromosomes(fasta_file)

    # remove gaps
    if options.gaps_file:
        chrom_segments = basenji.genome.split_contigs(chrom_segments, options.gaps_file)

    # ditch the chromosomes
    segments = []
    for chrom in chrom_segments:
        segments += [(chrom, seg_start, seg_end) for seg_start, seg_end in chrom_segments[chrom]]

    # filter for large enough
    segments = [cse for cse in segments if cse[2]-cse[1] >= options.seq_length]


    ################################################################
    # load model
    ################################################################
    if options.params_file:
        job = basenji.dna_io.read_job_params(options.params_file)
        job['num_targets'] = len(target_wigs)
        job['batch_size'] = 1024
        job['model'] = job.get('model','autoencoder')

        if job['model'] == 'autoencoder':
            model = basenji.autoencoder.AE(job)
            saver = tf.train.Saver()
        else:
            model = joblib.load(options.scent_file)

    ################################################################
    # bigwig read and process
    ################################################################
    print('Reading and pre-processing bigwigs')
    sys.stdout.flush()

    targets_real = []
    targets_imag = []

    targets_test = []
    test_indexes = []
    targets_n = 0

    filtered_n = 0

    update_i = 0

    # initialize multiprocessing pool
    pool = multiprocessing.Pool(options.processes)

    with tf.Session() as sess:
        if options.scent_file and job['model'] == 'autoencoder':
            saver.restore(sess, options.scent_file)

        # batch segment processing
        bstart = 0
        while bstart < len(segments):
            if update_i % 5 == 0:
                print('Tiling from %s:%d-%d' % segments[bstart])
                sys.stdout.flush()

            # determine batch end
            bend = batch_end(segments, bstart, 300000)

            # bigwig_read parameters
            bwr_params = [(wig_file, segments[bstart:bend], options.seq_length) for wig_file in target_wigs.values()]

            # pull the target values in parallel
            wig_targets = pool.starmap(bigwig_batch, bwr_params)

            # convert and transpose to S x L x T
            wig_targets = np.array(wig_targets)
            targets_wig = np.transpose(wig_targets, axes=(1,2,0))

            # filter boring segments
            prefilter_n = targets_wig.shape[0]
            targets_wig = filter_boring(targets_wig)
            filtered_n += prefilter_n - targets_wig.shape[0]

            # set aside test sequences
            test_n = int(options.test_pct*targets_wig.shape[0])
            test_bindexes = random.sample(range(targets_wig.shape[0]),test_n)
            targets_test.append(targets_wig[test_bindexes])
            test_indexes += [targets_n+tbi for tbi in test_bindexes]
            targets_n += targets_wig.shape[0]

            # map to latent space
            if options.scent_file is None:
                targets_latent = targets_wig
            else:
                targets_latent = latent_transform(sess, model, job, targets_wig)

            # compress across length
            if options.fourier_dim is None:
                targets_rfour = targets_latent
                targets_ifour = None
            else:
                targets_rfour, targets_ifour = fourier_transform(targets_latent, options.fourier_dim)

            # save
            targets_real.append(targets_rfour)
            targets_imag.append(targets_ifour)

            # update batch
            bstart = bend
            update_i += 1

    pool.close()

    # stack arrays
    targets_real = np.vstack(targets_real)
    if options.fourier_dim is not None:
        targets_imag = np.vstack(targets_imag)
    targets_test = np.vstack(targets_test)

    print('%d sequences' % targets_real.shape[0])
    print('%d filtered for low variability' % filtered_n)
    sys.stdout.flush()


    ################################################################
    # one hot code sequences
    ################################################################
    seqs_1hot, segments = segments_1hot(fasta_file, segments, options.seq_length)


    ################################################################
    # write to train, valid, test HDF5
    ################################################################

    # sample valid indexes (we already have test)
    valid_n = int(options.valid_pct*targets_n)
    nontest_indexes = set(range(targets_n)) - set(test_indexes)
    valid_indexes = random.sample(nontest_indexes, valid_n)

    # remainder is training
    train_indexes = list(nontest_indexes - set(valid_indexes))

    # training requires shuffle
    random.shuffle(train_indexes)

    # write to HDF5
    hdf5_out = h5py.File(hdf5_file, 'w')

    # HDF5 train
    hdf5_out.create_dataset('train_in', data=seqs_1hot[train_indexes], dtype='bool')
    hdf5_out.create_dataset('train_out', data=targets_real[train_indexes], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('train_out_imag', data=targets_imag[train_indexes], dtype='float16')

    # HDF5 valid
    hdf5_out.create_dataset('valid_in', data=seqs_1hot[valid_indexes], dtype='bool')
    hdf5_out.create_dataset('valid_out', data=targets_real[valid_indexes], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('valid_out_imag', data=targets_imag[valid_indexes], dtype='float16')

    # test
    hdf5_out.create_dataset('test_in', data=seqs_1hot[test_indexes], dtype='bool')
    hdf5_out.create_dataset('test_out', data=targets_real[test_indexes], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('test_out_imag', data=targets_imag[test_indexes], dtype='float16')
    hdf5_out.create_dataset('test_out_full', data=targets_test, dtype='float16')

    hdf5_out.close()

    '''
    # shuffle (little nervous about memory here)
    order = np.random.permutation(total_n)
    seqs_1hot = seqs_1hot[order]
    targets_real = targets_real[order]
    if options.fourier_dim is not None:
        targets_imag = targets_imag[order]

    # write to HDF5
    hdf5_out = h5py.File(hdf5_file, 'w')

    # train
    hdf5_out.create_dataset('train_in', data=seqs_1hot[:train_n], dtype='bool')
    hdf5_out.create_dataset('train_out', data=targets_real[:train_n], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('train_out_imag', data=targets_imag[:train_n], dtype='float16')

    # valid
    vi = train_n
    hdf5_out.create_dataset('valid_in', data=seqs_1hot[vi:vi+valid_n], dtype='bool')
    hdf5_out.create_dataset('valid_out', data=targets_real[vi:vi+valid_n], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('valid_out_imag', data=targets_imag[vi:vi+valid_n], dtype='float16')

    # test
    ti = train_n + valid_n
    hdf5_out.create_dataset('test_in', data=seqs_1hot[ti:], dtype='bool')
    hdf5_out.create_dataset('test_out', data=targets_real[ti:], dtype='float16')
    if options.fourier_dim is not None:
        hdf5_out.create_dataset('test_out_imag', data=targets_imag[ti:], dtype='float16')

    hdf5_out.close()
    '''


################################################################################
def batch_end(segments, bstart, batch_max):
    ''' Determine the batch end that will keep the
          batch length under the given max. '''

    bi = bstart
    blength = 0

    while bi < len(segments) and blength < batch_max:
        chrom, seg_start, seg_end = segments[bi]
        blength += seg_end - seg_start
        bi += 1

    bend = bi
    if bstart >= bend or bend > len(segments):
        print("I've made a terrible mistake. On batching segments", file=sys.stderr)
        exit(1)

    return bend


################################################################################
def bigwig_batch(wig_file, segments, seq_length):
    ''' Read a batch of segment values from a bigwig file

    Args:
      wig_file: Bigwig filename
      segments: list of (chrom,start,end) genomic segments to read,
                  assuming those segments are appropriate length
      seq_length: sequence length to break them into

    Returns:
      targets: target Bigwig value matrix
    '''

    # initialize target values
    targets = []

    # open wig
    wig_in = pyBigWig.open(wig_file)

    for chrom, seg_start, seg_end in segments:
        # read values
        try:
            seg_values = np.array(wig_in.values(chrom, seg_start, seg_end), dtype='float16')
        except:
            print("WARNING: %s doesn't see %s:%d-%d" % (wig_file,chrom,seg_start,seg_end))
            seg_values = np.array([np.nan]*(seg_end-seg_start), dtype='float16')

        # break up into batchable sequences (as below in segments_1hot)
        bstart = 0
        bend = bstart + seq_length
        while bend < len(seg_values):
            # append
            targets.append(seg_values[bstart:bend])

            # update
            bstart += seq_length
            bend += seq_length

    return targets


################################################################################
def filter_boring(targets, var_t=.01):
    ''' Filter boring segments without signal variance.

    Args
     targets: SxLxT array of target values
     var_t: Average variance threshold

    Returns:
     targets_exciting: SxLxT array of target values
    '''
    target_lvar_max = targets.var(axis=1).max(axis=1)
    exciting_indexes = [si for si in range(targets.shape[0]) if target_lvar_max[si] > var_t]
    return targets[exciting_indexes]


################################################################################
def fourier_transform(targets, dim):
    ''' Fourier transform.

    Args
     targets: SxLxT array of target values
     dim: # of fourier dimensions

    Returns:
     fourier_real: transformed targets, real component
     fourier_imag: transformed targets, imaginary component
    '''
    tn = targets.shape[2]
    fourier_real = np.zeros((targets.shape[0],dim,tn), dtype='float16')
    fourier_imag = np.zeros((targets.shape[0],dim,tn), dtype='float16')

    for ti in range(tn):
        fourier_ti = np.fft.rfft(targets[:,:,ti])[:,:dim]
        fourier_real[:,:,ti] = fourier_ti.real.astype('float16')
        fourier_imag[:,:,ti] = fourier_ti.imag.astype('float16')

    return fourier_real, fourier_imag


################################################################################
def latent_transform(sess, model, job, targets_wig):
    ''' Transform raw data to latent representation.

    Args
     sess: TensorFlow session
     model: TF or sklearn model
     job: dictionary of model hyper-parameters
     targets_wig: SxLxT array of target values

    Returns:
     targets_latent: SxDxT array of target values
    '''

    S, L, T = targets_wig.shape
    targets_length = targets_wig.reshape((S*L, T))

    if job['model'] == 'pca':
        targets_length_latent = model.transform(targets_length)
    else:
        batcher = basenji.batcher.BatcherT(targets_length, model.batch_size)
        targets_length_latent = model.latent(sess, batcher)

    targets_latent = targets_length_latent.reshape((S,L,job['latent_dim']))

    return targets_latent


################################################################################
def segments_1hot(fasta_file, segments, seq_length):
    ''' Read and 1-hot code sequences in their segment batches.

    Args
     fasta_file: FASTA genome
     segments: list of (chrom,start,end) genomic segments to read
     seq_length: sequence length to break them into

    Returns:
     seqs_1hot: You know.
     segments_used: A filtered list of only the (chrom,start,end) segments used
    '''

    # open fasta
    fasta = pysam.Fastafile(fasta_file)

    # initialize 1-hot coding list
    seqs_1hot = []

    # for status updates
    last_chrom = ''

    # save used segments
    segments_used = []

    for chrom, seg_start, seg_end in segments:
        if chrom != last_chrom:
            print(' %s' % chrom)

        if seg_start + seq_length <= seg_end:
            # read sequence
            seg_seq = fasta.fetch(chrom, seg_start, seg_end)

            # remember use
            segments_used.append((chrom, seg_start, seg_end))

            # break up into batchable sequences (as above in bigwig_batch)
            bstart = 0
            bend = bstart + seq_length
            while bend < len(seg_seq):
                # append
                seqs_1hot.append(basenji.dna_io.dna_1hot(seg_seq[bstart:bend]))

                # update
                bstart += seq_length
                bend += seq_length

        last_chrom = chrom

    return np.array(seqs_1hot), segments_used


################################################################################
if __name__ == '__main__':
    main()