#!/usr/bin/env python

import sys
import os
from shutil import copyfile
import urllib.request


# read paths

def make_directory(path):
    """Short summary.

    Parameters
    ----------
    path : Full path to the directory

    """

    if not os.path.isdir(path):
        os.mkdir(path)
        print("Making directory: " + path)
    else:
        print("Directory already exists!")

def process_file(urls_copy_path, output_path):
    with open(urls_copy_path, "r") as file:
        # read lines of the copy files
        urls = [f.strip() for f in file.readlines()]

    for url in urls:
        print("Downloading file "+url)
        output_path = os.path.join(output_dir, url.split('/')[-1])
        # download url
        urllib.request.urlretrieve(url, output_path)
        # once completed delete the url line that was just now processed
        urls = urls[1:]
        with open(urls_copy_path, 'w') as f:
            for u in urls:
                f.write("%s\n" % u)
    # once all done delete the copy file
    os.remove(urls_copy_path)

exp_folder = sys.argv[1]
exp_id = sys.argv[2]

urls_copy_path = os.path.join(exp_folder, "urls_copy.txt")
urls_path = os.path.join(exp_folder, exp_id+"_bigwig_urls.txt")
output_dir = os.path.join(exp_folder, exp_id)
make_directory(output_dir)

# look for existing copy file urls_copy.txt
# set paths and copy url file if not already present
if not os.path.isfile(urls_copy_path):
    # use this in the function that does the rest
    try:
        copyfile(urls_path, urls_copy_path)
    except:
        print('No urls.txt file provided!')

process_file(urls_copy_path, output_dir)
