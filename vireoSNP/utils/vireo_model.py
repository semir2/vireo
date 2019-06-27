# Core functions for Vireo model
# Author: Yuanhua Huang
# Date: 23/06/2019

# http://edwardlib.org/tutorials/probabilistic-pca
# https://github.com/allentran/pca-magic

import sys
import numpy as np
import multiprocessing
from itertools import permutations
from .vireo_base import get_ID_prob, get_GT_prob, get_theta_shapes
from .vireo_base import VB_lower_bound, tensor_normalize, loglik_amplify

def show_progress(RV=None):
    return RV

def vireo_flock(AD, DP, n_donor=None, K_amplify=1, n_init=20, n_proc=1, 
    random_seed=None, check_doublet=True, **kwargs):
    """
    """
    if random_seed is not None:
        np.random.seed(random_seed)

    print("[vireo] RUN1: %d random initializations..." %n_init)
    n_donor_run1 = round(n_donor * K_amplify)
    ID_prob_list = []
    for i in range(n_init):
        _ID_prob = np.random.rand(AD.shape[1], n_donor_run1)
        ID_prob_list.append(tensor_normalize(_ID_prob, axis=1))

    ## multiple initializations
    result = []

    # pool = multiprocessing.Pool(processes=n_proc)
    # for _ID_prob in ID_prob_list:
    #     result.append(pool.apply_async(vireo_core, (AD, DP, 
    #         n_donor=n_donor_run1, ID_prob_init=_ID_prob, **kwargs), 
    #         callback=show_progress))
    # pool.close()
    # pool.join()
    # result = [res.get() res for res in result]
    # print("")

    for _ID_prob in ID_prob_list:
        result.append(vireo_core(AD, DP, n_donor=n_donor_run1,
            ID_prob_init=_ID_prob, min_iter=5, max_iter=10, 
            verbose=False, check_doublet=False, **kwargs))
    
    LB_list = [x['LB_list'][-1] for x in result]
    print("All lower bounds:", LB_list)
    
    res1 = result[np.argmax(LB_list)]
    _donor_cnt = np.sum(res1['ID_prob'], axis=0)
    _donor_idx = np.argsort(_donor_cnt)[::-1]
    print("Lower bound:", res1['LB_list'][-1])
    print("\t".join(["donor%d" %x for x in _donor_idx]))
    print("\t".join(["%.0f" %_donor_cnt[x] for x in _donor_idx]))
    
    print(res1['theta_shapes'])

    ## second run
    print(("[vireo] RUN2: Tuning the largest %d donors in RUN1 "
           "as a start point" %n_donor))
    _ID_prob = res1['ID_prob'][:, _donor_idx[:n_donor]]
    _ID_prob[_ID_prob < 10**-10] = 10**-10
    print(_ID_prob.shape)
    res1 = vireo_core(AD, DP, n_donor=n_donor, ID_prob_init=_ID_prob, 
                      **kwargs) #theta_init=res1['theta_shapes'], 
    _donor_cnt = np.sum(res1['ID_prob'], axis=0)
    _donor_idx = np.argsort(_donor_cnt)[::-1]
    print("Lower bound:", res1['LB_list'][-1])
    print("\t".join(["donor%d" %x for x in _donor_idx]))
    print("\t".join(["%.0f" %_donor_cnt[x] for x in _donor_idx]))
    
    return res1


def vireo_core(AD, DP, n_donor=None, GT_prior=None, learn_GT=True,
    theta_prior=None, learn_theta=True, Psi=None, ID_prob_init=None, 
    theta_init=None,
    doublet_prior=None, check_doublet=True, min_iter=20, max_iter=200, 
    epsilon_conv=1e-2, random_seed=None, verbose=False):
    """
    """
    if random_seed is not None:
        np.random.seed(random_seed)

    if n_donor is None:
        if len(GT_prior.shape) < 3 or GT_prior.shape[2] < 2:
            print("Error: no n_donor and GT_prior has < 2 donors.")
            sys.exit(1)
        else:
            n_donor = GT_prior.shape[2]
        
    n_var = AD.shape[0] # n_variants and n_cells
    
    ## initialize thete
    if theta_prior is None:
        #theta_prior = np.array([[0.3, 29.7], [3, 3], [29.7, 0.3]])
        theta_prior = np.array([[0.1, 99.9], [50, 50], [99.9, 0.1]])
    if theta_init is None:
        theta_shapes = theta_prior.copy()
    else:
        theta_shapes = theta_init.copy()

    ## initialize Psi
    if Psi is None:
        Psi = np.ones(n_donor) / n_donor
    else:
        Psi = Psi[:n_donor] / np.sum(Psi[:n_donor])
    if ID_prob_init is None:
        ID_prob = tensor_normalize(np.random.rand(AD.shape[1], n_donor), axis=1)
    else:
        ID_prob = tensor_normalize(ID_prob_init.copy(), axis=1)
    
    ## initialize GT
    if GT_prior is None:
        GT_prior = tensor_normalize(np.ones((n_var, 3, n_donor)), axis=1)
        GT_prob, logLik_GT = get_GT_prob(AD, DP, ID_prob, 
                                         theta_shapes, GT_prior)
        if learn_GT is False:
            print("As GT_prior is not given, we change learn_GT to True.")
            learn_GT = True
    else:
        GT_prob = GT_prior.copy()

    #TODO: check if there is a better way to deal with GT imcompleteness
    if GT_prior.shape[2] < n_donor:
        _add_n = n_donor - GT_prior.shape[2]
        GT_prior = np.append(GT_prior, 
            tensor_normalize(np.ones((n_var, 3, _add_n)), axis=1), axis=2)
        GT_prob = GT_prior.copy()
        if learn_GT is False:
            print("As GT_prior is not complete, we change learn_GT to True.")
            learn_GT = True
    elif GT_prior.shape[2] > n_donor:
        print("Warning: n_donor is smaller than samples in GT_prior, hence we "
              "ignore n_donor.")
        n_donor = GT_prior.shape[2]

    ## VB interations
    LB = np.zeros(max_iter)
    for it in range(max_iter):
        ID_prob, GT_prob, theta_shapes, LB[it] = update_VB(AD, DP, GT_prob, 
            theta_shapes, theta_prior, GT_prior, Psi, doublet_prior,
            learn_GT=learn_GT, learn_theta=learn_theta, check_doublet=False)

        if it > min_iter:
            if LB[it] < LB[it - 1]:
                if verbose:
                    print("Warning: Lower bound decreases!\n")
            elif it == max_iter - 1: 
                if verbose:
                    print("Warning: VB did not converge!\n")
            elif LB[it] - LB[it - 1] < epsilon_conv:
                break

    ## check doublet
    if check_doublet:
        ID_prob2, GT_prob, theta_shapes, LB_doublet = update_VB(AD, DP, GT_prob, 
            theta_shapes, theta_prior, GT_prior, Psi, doublet_prior,
            learn_GT=True, learn_theta=True, check_doublet=True)

        ID_prob = ID_prob2[:, :n_donor]
        doublet_prob = ID_prob2[:, n_donor:]
    else:
        LB_doublet = None
        n_donor_doublt = int(n_donor * (n_donor - 1) / 2)
        doublet_prob = np.zeros((ID_prob.shape[0], n_donor_doublt))

    RV = {}
    RV['ID_prob'] = ID_prob
    RV['GT_prob'] = GT_prob
    RV['doublet_prob'] = doublet_prob
    RV['theta_shapes'] = theta_shapes
    RV['LB_list'] = LB[: it+1]
    RV['LB_doublet'] = LB_doublet
    return RV


def update_VB(AD, DP, GT_prob, theta_shapes, theta_prior, GT_prior, 
    Psi, doublet_prior=None, learn_GT=True, learn_theta=True, 
    check_doublet=False):
    """
    Update the parameters of each component of the variantional 
    distribution. 
    
    The doublet probability can be created by doublet genotypes
    """
    if check_doublet:
        GT_both = add_doublet_GT(GT_prob)
        theta_both = add_doublet_theta(theta_shapes)
        if doublet_prior is None:
            doublet_prior = 1 - GT_prob.shape[2] / GT_both.shape[2]
        Psi_both = np.ones(GT_both.shape[2]) * doublet_prior
        Psi_both[:GT_prob.shape[2]] = Psi * (1 - doublet_prior)
    else:
        Psi_both = Psi.copy()
        GT_both = GT_prob.copy()
        theta_both = theta_shapes.copy()

    ID_prob2, logLik_ID = get_ID_prob(AD, DP, GT_both, theta_both, Psi_both)
    ID_prob = ID_prob2[:, :GT_prob.shape[2]]
    
    if learn_GT:
        GT_prob, logLik_GT = get_GT_prob(AD, DP, ID_prob, 
                                         theta_shapes, GT_prior)
    if learn_theta:
        theta_shapes = get_theta_shapes(AD, DP, ID_prob, 
                                        GT_prob, theta_shapes)
    
    ### check how to calculate lower bound for when detecting doublets
    LB_val = VB_lower_bound(logLik_ID, GT_prob, ID_prob2, theta_shapes, 
                            theta_prior, GT_prior, Psi_both)

    return ID_prob2, GT_prob, theta_shapes, LB_val


def add_doublet_theta(theta_shapes):
    """
    calculate theta for doublet genotype: GT=0&1 and GT=1&2 by
    averaging thire beta paramters
    
    Example
    -------
    theta_shapes = np.array([[0.3, 29.7], [3, 3], [29.7, 0.3]])
    add_doublet_theta(theta_shapes)
    """
    #doublet GT: 0_1 and 1_2
    theta_shapes2 = np.zeros((2,2)) 
    for ii in range(2):
        theta_use  = theta_shapes[ii:(ii + 2), :]
        theta_mean = np.mean(tensor_normalize(theta_use, axis=1), axis=0)
        shape_sum  = np.sqrt(np.sum(theta_use[0, :]) * np.sum(theta_use[1, :]))
        theta_shapes2[ii, :] = theta_mean * shape_sum
    return np.append(theta_shapes, theta_shapes2, axis=0)


def add_doublet_GT(GT_prob):
    """
    Add doublet genotype by summarizing their probability:
    New GT has five categories: 0, 1, 2, 1.5, 2.5
    """
    db_idx = np.array(list(permutations(range(GT_prob.shape[2]), 2)))
    idx1 = db_idx[:, 0]
    idx2 = db_idx[:, 1]
    
    ## GT_prob has three genotypes: 0, 1, 2;
    GT_prob2 = np.zeros((GT_prob.shape[0], 5, db_idx.shape[0]))
    
    GT_prob2[:, 0, :] = (GT_prob[:, 0, idx1] * GT_prob[:, 0, idx2])
    GT_prob2[:, 1, :] = (GT_prob[:, 0, idx1] * GT_prob[:, 2, idx2] +
                         GT_prob[:, 1, idx1] * GT_prob[:, 1, idx2] +
                         GT_prob[:, 2, idx1] * GT_prob[:, 0, idx2])
    GT_prob2[:, 2, :] = (GT_prob[:, 2, idx1] * GT_prob[:, 2, idx2])
    GT_prob2[:, 3, :] = (GT_prob[:, 0, idx1] * GT_prob[:, 1, idx2] + 
                         GT_prob[:, 1, idx1] * GT_prob[:, 0, idx2])
    GT_prob2[:, 4, :] = (GT_prob[:, 1, idx1] * GT_prob[:, 2, idx2] + 
                         GT_prob[:, 2, idx1] * GT_prob[:, 1, idx2])
    
    GT_prob2 = tensor_normalize(GT_prob2, axis=1)
    GT_prob1 = np.append(GT_prob, np.zeros((GT_prob.shape[0], 2, 
                                            GT_prob.shape[2])), axis=1)
    return np.append(GT_prob1, GT_prob2, axis=2)
    