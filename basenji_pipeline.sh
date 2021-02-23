#!/bin/bash

# ARGUMENTS
data=$1 # e.g. /home/shush/profile/QuantPred/datasets/HepG2
biosample=$2 # e.g. HepG2
filetype=$3 # e.g. raw
outdir_data=$4 # e.g. /home/shush/profile/basenji/data

label=${biosample}_${filetype}
genome_size=/home/shush/genomes/GRCh38_EBV.chrom.sizes.tsv
genome=/home/shush/genomes/hg38.fa
input_size=1024
pool_window=32
d=1 #take all without downsampling
unmap=data/GRCh38_unmap.bed
samplefile_dir="$outdir_data/sample_files"

out_label_dir="${outdir_data}/$label"
in_label_dir="${data}/${label}"

# create samplefile for basset AND basenji using existing data folder
bin/create_samplefile.py "$in_label_dir" "$data/summary.csv" $biosample $filetype $samplefile_dir

# select best bed from basset preprocessing

/home/shush/profile/QuantPred/bed_generation.py -y -m 200 -s $input_size \
                                                -o "$in_label_dir/$label" \
                                                -c $genome_size \
                                                "$samplefile_dir/basset_sample_beds_${biosample}.txt"

bedfile="$in_label_dir/$label.bed"
sorted_bedfile="$in_label_dir/sorted_$label.bed"
sorted_genome="$in_label_dir/sorted_genome.bed"
sort -k1,1 -k2,2n $bedfile > $sorted_bedfile
sort -k1,1 -k2,2n $genome_size > $sorted_genome
bedtools complement -i $sorted_bedfile -g $sorted_genome > nonpeaks.bed
cat nonpeaks.bed $unmap > avoid_regions.bed
sort -k1,1 -k2,2n avoid_regions.bed > sorted_avoid_regions.bed
bedtools merge -i sorted_avoid_regions.bed > "$outdir_data/merged_avoid_regions.bed"

rm nonpeaks.bed
rm avoid_regions.bed
rm sorted_avoid_regions.bed


# preprocess data using GRCh38, and using the bed file to select regions
bin/org_basenji_data.py /home/shush/genomes/hg38.fa \
                                    "$samplefile_dir/basenji_sample_$label.txt" \
                                    -g "$outdir_data/merged_avoid_regions.bed" \
                                    -l $input_size -o $out_label_dir -t .1 -v .1 \
                                    -w $pool_window --local -d $d

scp "$outdir_data/merged_avoid_regions.bed" "$out_label_dir/"
rm "$outdir_data/merged_avoid_regions.bed"
