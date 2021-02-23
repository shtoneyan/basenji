#!/usr/bin/env python
import os
import pandas as pd
import sys
import util
from pathlib import Path

data_dir = sys.argv[1] #'/home/shush/profile/QuantPred/datasets/HepG2/fold'
summary_file = sys.argv[2] #'/home/shush/profile/QuantPred/datasets/HepG2/summary.csv'
label = sys.argv[3] #'HepG2'
subfolder = sys.argv[4] #'raw'
outdir = sys.argv[5]

assert subfolder in ['raw', 'sign', 'fold'], 'Unknown folder name'

if subfolder == 'raw':
    filetype = 'bam'
else:
    filetype = subfolder
util.make_directory(outdir)

bed_dir = os.path.join(Path(data_dir).parent, 'bed')

summary_df = pd.read_csv(summary_file, index_col=0)

bedfiles = [i[-1] for i in summary_df['bed'].str.split('/')]
bedpaths = [os.path.join(bed_dir, f) for f in bedfiles]

bed_labels = summary_df['label']


with open(os.path.join(outdir, 'basset_sample_beds_{}.txt'.format(label)), 'w') as filehandle:
    for i in range(len(bed_labels)):
        filehandle.write('{}\t{}\n'.format(bed_labels[i], bedpaths[i]))


xfiles = [i[-1] for i in summary_df[filetype].str.split('/')]
identifiers = [i.split('.')[0] for i in xfiles]
paths = [os.path.join(Path(data_dir).parent, label+'_'+subfolder, f) for f in xfiles]
if subfolder == 'raw':
    paths = [i.split('.bam')[0]+'.bw' for i in paths]

first_line = '\t'.join(['index', 'identifier', 'file', 'clip', 'sum_stat', 'description'])

with open(os.path.join(outdir, 'basenji_sample_{}.txt'.format(label+'_'+subfolder)), 'w') as filehandle:
    filehandle.write('{}\n'.format(first_line))
    for i in range(len(paths)):
        filehandle.write('{}\t{}\t{}\t{}\t{}\t{}\n'.format(i, identifiers[i],
                                                       paths[i], '384',
                                                       'sum', summary_df['label'][i]))
