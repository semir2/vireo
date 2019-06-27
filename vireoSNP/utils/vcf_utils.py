# Utilility functions for processing vcf files
# Author: Yuanhua Huang
# Date: 24/06/2019

import os
import sys
import gzip
import h5py
import subprocess
import numpy as np

def parse_sample_info(sample_dat, sparse=True):
    """
    Parse genotype information for each sample
    Note, it requires the format for each variants to 
    be the same.
    """
    if sample_dat == [] or sample_dat is None:
        return None

    # require the same format for all variants
    format_all = [x[0] for x in sample_dat]
    if format_all.count(format_all[0]) != len(format_all):
        print("Error: require the same format for all variants.")
        exit()
    format_list = format_all[0].split(":")
    
    RV = {}
    for _format in format_list:
        RV[_format] = []
    if sparse:
        RV['indices'] = []
        RV['indptr'] = [0]
        RV['shape'] = (len(sample_dat[0][1:]), len(sample_dat))
        missing_val = ":".join(["."] * len(format_list))
        
        cnt = 0
        for j in range(len(sample_dat)): #variant j
            _line = sample_dat[j]
            for i in range(len(_line[1:])): #cell i
                if _line[i+1] == missing_val:
                    continue
                _line_key = _line[i+1].split(":")
                for k in range(len(format_list)):
                    RV[format_list[k]].append(_line_key[k])

                cnt += 1
                RV['indices'].append(i)
            RV['indptr'].append(cnt)
    else:
        for _line in sample_dat:
            _line_split = [x.split(":") for x in _line[1:]]
            for k in range(len(format_list)):
                _line_key = [x[k] for x in _line_split]
                RV[format_list[k]].append(_line_key)
    return RV


def load_VCF(vcf_file, biallelic_only=False, load_sample=True, sparse=True):
    """
    Load whole VCF file 
    -------------------
    Initially designed to load VCF from cellSNP output, requiring 
    1) all variants have the same format list;
    2) a line starting with "#CHROM", with sample ids.
    If these two requirements are satisfied, this function also supports general
    VCF files, e.g., genotype for multiple samples.

    Note, it may take a large memory, please filter the VCF with bcftools first.
    """
    if vcf_file[-3:] == ".gz" or vcf_file[-4:] == ".bgz":
        infile = gzip.open(vcf_file, "rb")
        is_gzip = True
    else:
        infile = open(vcf_file, "r")
        is_gzip = False
    
    FixedINFO = {}
    contig_lines = []
    comment_lines = []
    var_ids, obs_ids, obs_dat = [], [], []
    
    for line in infile:
        if is_gzip:
            line = line.decode('utf-8')
        if line.startswith("#"):
            if line.startswith("##contig="):
                contig_lines.append(line.rstrip())
            if line.startswith("#CHROM"):
                obs_ids = line.rstrip().split("\t")[9:]
                key_ids = line[1:].rstrip().split("\t")[:8]
                for _key in key_ids:
                    FixedINFO[_key] = []
            else:
                comment_lines.append(line.rstrip())
        else:
            list_val = line.rstrip().split("\t") #[:5] #:8
            if biallelic_only:
                if len(list_val[3]) > 1 or len(list_val[4]) > 1:
                    continue
            if load_sample:
                obs_dat.append(list_val[8:])
            for i in range(len(key_ids)):
                FixedINFO[key_ids[i]].append(list_val[i])
            var_ids.append("_".join([list_val[x] for x in [0, 1, 3, 4]]))
    infile.close()

    RV = {}
    RV["variants"]  = var_ids
    RV["FixedINFO"] = FixedINFO
    RV["samples"]   = obs_ids
    RV["GenoINFO"]  = parse_sample_info(obs_dat, sparse=sparse)
    RV["contigs"]   = contig_lines
    RV["comments"]  = comment_lines
    return RV


def write_VCF_to_hdf5(VCF_dat, out_file):
    """
    Write vcf data into hdf5 file
    """
    f = h5py.File(out_file, 'w')
    f.create_dataset("contigs", data=np.string_(VCF_dat['contigs']), 
                     compression="gzip", compression_opts=9)
    f.create_dataset("samples", data=np.string_(VCF_dat['samples']), 
                     compression="gzip", compression_opts=9)
    f.create_dataset("variants", data=np.string_(VCF_dat['variants']), 
                     compression="gzip", compression_opts=9)
    f.create_dataset("comments", data=np.string_(VCF_dat['comments']), 
                     compression="gzip", compression_opts=9)
    
    ## variant fixed information
    fixed = f.create_group("FixedINFO")
    for _key in VCF_dat['FixedINFO']:
        fixed.create_dataset(_key, data=np.string_(VCF_dat['FixedINFO'][_key]), 
                             compression="gzip", compression_opts=9)
        
    ## genotype information for each sample
    geno = f.create_group("GenoINFO")
    for _key in VCF_dat['GenoINFO']:
        geno.create_dataset(_key, data=np.string_(VCF_dat['GenoINFO'][_key]), 
                             compression="gzip", compression_opts=9)
        
    f.close()


def read_sparse_GeneINFO(GenoINFO, keys=['AD', 'DP'], axes=[-1, -1]):
    M, N = np.array(GenoINFO['shape']).astype('int')
    indptr = np.array(GenoINFO['indptr']).astype('int')
    indices = np.array(GenoINFO['indices']).astype('int')
    
    from scipy.sparse import csr_matrix
    
    RV = {}
    for i in range(len(keys)):
        _dat = [x.split(",")[axes[i]] for x in GenoINFO[keys[i]]]
        _dat = [x if x != '.' else '0' for x in _dat]
        data = np.array(_dat).astype('float')
        RV[keys[i]] = csr_matrix((data, indices, indptr), shape=(N, M))
    return RV


def GenoINFO_maker(GT_prob, AD_reads, DP_reads):
    """
    Generate the Genotype information for estimated genotype probability at
    sample level.
    """
    GT_val = np.argmax(GT_prob, axis=1)
    GT_prob[GT_prob < 10**(-10)] = 10**(-10)
    PL_prob = np.round(-10 * np.log10(GT_prob)).astype(int).astype(str)
    AD_reads = np.round(AD_reads).astype(int).astype(str)
    DP_reads = np.round(DP_reads).astype(int).astype(str)

    GT, PL, AD, DP = [], [], [], []
    for i in range(GT_prob.shape[0]):
        GT.append([['0/0', '1/0', '1/1'][x] for x in GT_val[i, :]])
        PL.append([",".join(list(x)) for x in PL_prob[i, :, :].transpose()])
        AD.append(list(AD_reads[i, :]))
        DP.append(list(DP_reads[i, :]))
    
    RV = {}
    RV['GT'] = GT
    RV['AD'] = AD
    RV['DP'] = DP
    RV['PL'] = PL
    return RV


def write_VCF(out_file, VCF_dat, GenoTags=['GT', 'AD', 'DP', 'PL']):
    if out_file.endswith(".gz"):
        out_file_use = out_file.split(".gz")[0]
    else:
        out_file_use = out_file
        
    fid_out = open(out_file_use, "w")
    for line in VCF_dat['comments']:
        fid_out.writelines(line + "\n")
    
    VCF_COLUMN = ["CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", 
                  "INFO", "FORMAT"]
    fid_out.writelines("#" + "\t".join(VCF_COLUMN + VCF_dat['samples']) + "\n")
    
    for i in range(len(VCF_dat['variants'])):
        line = [VCF_dat['FixedINFO'][x][i] for x in VCF_COLUMN[:8]]
        line.append(":".join(GenoTags))

        for d in range(len(VCF_dat['GenoINFO'][GenoTags[0]][0])):
            _line_tag = [VCF_dat['GenoINFO'][x][i][d] for x in GenoTags]
            line.append(":".join(_line_tag))
        fid_out.writelines("\t".join(line) + "\n")
    fid_out.close()

    import shutil
    if shutil.which("bgzip") is not None:
        bashCommand = "bgzip -f %s" %(out_file_use)
    else:
        bashCommand = "gzip -f %s" %(out_file_use)
    pro = subprocess.Popen(bashCommand.split(), stdout=subprocess.PIPE)
    pro.communicate()[0]

    
def parse_donor_GPb(GT_dat, tag='GT'):
    """
    Parse the donor genotype probability
    tag: GT, GP, or PL
    """
    def parse_GT_code(code, tag):
        if code == ".":
            return np.array([1/3, 1/3, 1/3])
        if tag == 'GT':
            _prob = np.array([0, 0, 0])
            _prob[int(float(code[0]) + float(code[-1]))] = 1
        elif tag == 'GP':
            _prob = np.array(code.split(','), float)
        elif tag == 'PL':
            _prob = 10**(-0.1 * np.array(code.split(','), float) - 0.025) # 0?
        else:
            _prob = None
        return _prob / np.sum(_prob)

    if ['GT', 'GP', 'PL'].count(tag) == 0:
        print("[parse_donor_GPb] Error: no support tag: %s" %tag)
        return None

    GT_prob = np.zeros((len(GT_dat), 3, len(GT_dat[0])))
    for i in range(GT_prob.shape[0]):
        for j in range(GT_prob.shape[2]):
            GT_prob[i, :, j] = parse_GT_code(GT_dat[i][j], tag)

    return GT_prob