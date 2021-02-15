#!/usr/bin/env python
import os
import pandas as pd

data_dir = '/home/shush/profile/QuantPred/datasets/HepG2/fold'
summary_file = '/home/shush/profile/QuantPred/datasets/HepG2/summary.csv'
label = 'HepG2'

summary_df = pd.read_csv(summary_file)

label_dict = {}
for i, row in summary_df.iterrows():
    label_dict[''.join(row.iloc[2:].values)] = row['label']

prefixes = []
paths = []
descriptions = []
for file in os.listdir(data_dir):

    prefixes.append(file.split('.')[0])
    paths.append(os.path.join(data_dir, file))
    for k,v in label_dict.items():
        if file in k:
            descriptions.append(v)

first_line = '\t'.join(['index', 'identifier', 'file', 'clip', 'sum_stat', 'description'])
with open('sample_{}.txt'.format(label), 'w') as filehandle:
    filehandle.write('{}\n'.format(first_line))
    for i in range(len(paths)):
        filehandle.write('{}\t{}\t{}\t{}\t{}\t{}\n'.format(i, prefixes[i],
                                                       paths[i], '384',
                                                       'sum', descriptions[i]))
