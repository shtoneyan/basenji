#!/usr/bin/env python

import pandas as pd
import numpy as np
import sys
import os
import download_urls

encode_metadata_path = sys.argv[1] #'encode_dnase.tsv'
selection_path = sys.argv[2] #'basenji_dnase.xlsx'
data_dir = sys.argv[3]
exp_id = sys.argv[4]

# large selection of encode files in a metadata format
encode_df = pd.read_csv(encode_metadata_path, sep='\t')
# selection of interest to replicate
basenji_df = pd.read_excel(selection_path,engine='openpyxl')

genome_assembly = 'hg19'

file_id = list(basenji_df['Identifier'].values)
outputs = []
for file_accession in file_id:
    df = encode_df[encode_df['Experiment accession']==file_accession]
    filtered_df = df[(df['File format'] == 'bigWig')&(df['File assembly'] == genome_assembly)&(df['Output type'] == 'read-depth normalized signal')]
    n_files = [len(files) for files in list(filtered_df['Derived from'].values)]
    if len(n_files)>0:
        arbitrary_id = np.argmax(n_files)
        bigwig_url = list(filtered_df['File download URL'].values)[arbitrary_id]
        outputs.append(bigwig_url)
outputs = list(set(outputs))

with open(os.path.join(data_dir, exp_id+'_bigwig_urls.txt'), 'w') as f:
    for item in outputs:
        f.write("%s\n" % item)
