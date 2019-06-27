#!/bin/sh

## Input files
CELL_FILE=data/cells.cellSNP.vcf.gz
DONOR_FILE=data/donors.cellSNP.vcf.gz

## MODE 1: no genotype
OUT_DIR=data/cellSNP_noGT
vireo -c $CELL_FILE -N 4 -o $OUT_DIR --randSeed 2

## MODE 2: given genotype
# OUT_DIR=data/cellSNP_GT
# vireo -c $CELL_FILE -d $DONOR_FILE -o $OUT_DIR --randSeed 2 --genoTag GT


# CELL_FILE=data/cells.donorid.vcf.gz
# OUT_DIR=data/donorid_noGT
# vireo -c $CELL_FILE -N 3 -o $OUT_DIR