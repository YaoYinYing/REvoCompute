# Copyright (C) 2024-2026 YaoYinYing
# SPDX-License-Identifier: GPL-3.0-only
"""Checked-in transcription of the pinned GREMLIN_LH notebook's reusable cells.

This module is a literal, human-reviewed transcription of the code cells that
``generate_upstream_reference.py`` rebuilds the upstream module state from.  It
replaces the previous approach of ``exec``-ing the notebook: an auditable
transcription cannot execute arbitrary code from a caller-supplied path, and the
faithfulness guard below ties the transcription back to the pinned blob.

Pinned source (see ``tests/data/gremlin_lh/upstream_reference.json``):

* git blob ``PINNED_NOTEBOOK_BLOB``
* SHA-256 ``PINNED_NOTEBOOK_SHA256``

Transcribed cells: 7 (``parse_fasta``/``parse_aln``/``alphabet``/``mk_msa``),
8 (``get_mtx``/``get_pair_pssm``/``get_pssm``), 11 (the JAX covariance,
weighting, APC, regularizer, loss, and Adam definitions), 13 (``GREMLIN``), and
14 (``get_Hamiltonian_loss``/``get_Hamiltonian``).

The two REvoCompute-documented corrections (``SCIENTIFIC_TRACEABILITY.md`` §3)
are **parameters whose default is the notebook's own behaviour**, so this single
transcription produces every variant the receipt needs with no textual
substitution of source at run time:

* **D1** — ``gap_plane_index`` selects the alphabet plane used as the gap plane by
  ``jax_weights``.  The pinned notebook reads plane ``-1``, a stale index from
  the pre-``gap``-first alphabet; under the pinned alphabet that plane is
  tyrosine, so the correction reads plane ``0``.
* **D2** — ``field_penalty_floor`` selects the one-body field L2 penalty
  operator.  The pinned notebook uses integer floor division; the correction
  uses ordinary division, as every sibling regularizer term does.

``assert_matches_pinned_notebook`` renders each transcription back to its pinned
form (dropping the correction parameters, which are ours) and refuses unless the
result appears verbatim in the pinned cell.
"""
from __future__ import annotations

import functools
import inspect
from typing import Callable

import jax
import jax.numpy as jnp
import numpy as np
import optax
import string
from jax import tree_util

#: Cell indices in the pinned notebook blob.
CELL_UTILS = 7
CELL_MTX = 8
CELL_GREMLIN = 11
CELL_FIT = 13
CELL_HAMILTONIAN = 14

#: Pinned notebook identity.  The blob hash is what actually pins the transcribed
#: source; the commit is recorded in the receipt but cannot be recomputed offline.
PINNED_NOTEBOOK_BLOB = "79cc0fdaba25ff1a6d6cb12ab2a2ebc8358c2c17"
PINNED_NOTEBOOK_SHA256 = "7f4638aeb835689717a7b497d182cee3bac24128add71a3a7c1c542ddc50c3dc"

#: Corrections, expressed as the pinned default and the corrected value.
GAP_PLANE_PINNED = -1
GAP_PLANE_CORRECTED = 0
FIELD_PENALTY_FLOOR_PINNED = True
FIELD_PENALTY_FLOOR_CORRECTED = False

#: The three variants the receipt records, as (gap_plane_index, field_penalty_floor).
VARIANTS: dict[str, tuple[int, bool]] = {
    "expected": (GAP_PLANE_CORRECTED, FIELD_PENALTY_FLOOR_CORRECTED),
    "d1_only": (GAP_PLANE_CORRECTED, FIELD_PENALTY_FLOOR_PINNED),
    "pinned_uncorrected": (GAP_PLANE_PINNED, FIELD_PENALTY_FLOOR_PINNED),
}

#: Functions transcribed from each pinned cell, in definition order.
TRANSCRIBED: dict[int, tuple[str, ...]] = {
    CELL_UTILS: ("parse_fasta", "parse_aln", "mk_msa"),
    CELL_MTX: ("get_mtx", "get_pair_pssm", "get_pssm"),
    CELL_GREMLIN: (
        "jax_cov",
        "jax_weights",
        "jax_apc",
        "jax_inv_cov",
        "categorical_crossentropy",
        "reg_LH",
        "compute_loss",
        "compute_reg",
        "compute_loss_bias",
        "get_H",
        "custom_adam",
    ),
    CELL_FIT: ("GREMLIN",),
    CELL_HAMILTONIAN: ("get_Hamiltonian_loss", "get_Hamiltonian"),
}


# ── cell 7: alignment parsing, alphabet, one-hot encoding ─────────────────────


def parse_fasta(filename, a3m=False):
  '''function to parse fasta file'''

  if a3m:
    # for a3m files the lowercase letters are removed
    # as these do not align to the query sequence
    rm_lc = str.maketrans(dict.fromkeys(string.ascii_lowercase))

  header, sequence = [],[]
  lines = open(filename, "r")
  for line in lines:
    line = line.rstrip()
    if len(line)>0:
      if line[0] == ">":
        header.append(line[1:])
        sequence.append([])
      else:
        if a3m: line = line.translate(rm_lc)
        else: line = line.upper()
        sequence[-1].append(line)
  lines.close()
  sequence = [''.join(seq) for seq in sequence]

  return header, sequence

def parse_aln(filename):
  '''function to parse fasta file'''
  sequence = []
  lines = open(filename, "r")
  for line in lines:
    line = line.rstrip()
    line = line.upper()
    sequence.append(line)
  lines.close()

  return sequence

alphabet =  "-ACDEFGHIKLMNPQRSTVWY"

def mk_msa(seqs):
  '''one hot encode msa'''
  #alphabet = "ARNDCQEGHILKMFPSTWYV-"
  states = len(alphabet)
  a2n = {a:n for n,a in enumerate(alphabet)}
  msa_ori = np.array([[a2n.get(aa, states-1) for aa in seq] for seq in seqs])
  return msa_ori,np.eye(states)[msa_ori]


# ── cell 8: two-body matrices and PSSM ───────────────────────────────────────


def get_mtx(W):
  '''return L*L matrices given by two body term'''
  # l2norm of 20x20 matrices (note: we ignore gaps)
  raw = np.sqrt(np.sum(np.square(W),(1,3)))
  np.fill_diagonal(raw,0)
  # apc (average product correction)
  ap = np.sum(raw,0,keepdims=True)*np.sum(raw,1,keepdims=True)/np.sum(raw)
  apc = raw - ap
  np.fill_diagonal(apc,0)

  return(raw,apc)

def get_pair_pssm(msa,msa_weights=None):
  '''input: (number of samples, length, states) = (N, L, K)
  output: (L, K, L, K)'''
  if msa_weights is None:
    msa_weights = np.ones(msa.shape[0])
  msa = msa * np.sqrt(1e-8 + msa_weights)[:,None,None]
  return (np.tensordot(msa,msa, [0,0])/np.sum(msa_weights))

def get_pssm(msa,msa_weights=None):
  if msa_weights is None:
    msa_weights = np.ones(msa.shape[0])
  return (np.sum(msa*msa_weights[:,None,None],0))/np.sum(msa_weights)


# ── cell 11: JAX covariance, weighting, APC, regularizers, loss, Adam ────────


def jax_cov(x, w=None, do_mean=True):
    '''compute weighted covariance matrix'''
    if w is None:
        num_points = x.shape[0] - 1
        if do_mean:
            x_mean = jnp.mean(x, axis=0, keepdims=True)
            x = (x - x_mean)
    else:
        num_points = jnp.sum(w) - jnp.sqrt(jnp.mean(w))
        if do_mean:
            x_mean = jnp.sum(x * w[:, None], axis=0, keepdims=True) / num_points
            x = (x - x_mean) * jnp.sqrt(w[:, None])
        else:
            x = x * jnp.sqrt(w[:, None])
    return jnp.matmul(x.T, x) / num_points


def jax_weights(x_msa, w_lam=0.8, gap_cutoff=0.5, gap_plane_index=GAP_PLANE_PINNED):
    '''compute weight for each sequence'''

    x_nongap = (jnp.mean(x_msa[:, :, gap_plane_index], axis=0) < gap_cutoff).astype(jnp.float32)
    x_msa_nongap = x_msa * x_nongap[None, :, None]
    x_ln = jnp.sum(x_nongap)
    x_pw = jnp.tensordot(x_msa_nongap, x_msa_nongap, [[1, 2], [1, 2]]) / x_ln
    x_cut = x_pw >= w_lam
    return 1.0 / jnp.sum(x_cut, -1)

def jax_apc(x_w, return_raw=False):
    '''Average Product Correction'''

    w_sq = jnp.square(x_w)
    x_wi = jnp.sqrt(jnp.sum(w_sq, axis=(1, 3)) + 1e-8)
    x_wi = x_wi - jnp.diag(jnp.diag(x_wi))
    x_ap_sum = jnp.sum(x_wi, axis=0)
    x_ap = x_ap_sum[None, :] * x_ap_sum[:, None] / jnp.sum(x_ap_sum)
    x_wip = (x_wi - x_ap)
    x_wip = x_wip - jnp.diag(jnp.diag(x_wip))
    if return_raw:
        return x_wi, x_wip
    else:
        return x_wip


def jax_inv_cov(X, X_W, lam_w=4.5, pcc=False, do_mean=True, rm_diag=False, weights_pc=True):
    x_nr, x_nc, cat = X.shape
    x_msa = X
    x_feat = jnp.reshape(x_msa, (x_nr, x_nc * cat))

    if weights_pc:
        x_weights = X_W
    else:
        x_weights = jax_weights(x_msa)  # Assuming jax_weights is already defined

    # Compute covariance
    x_c = jax_cov(x_feat, x_weights, do_mean=do_mean)  # Assuming jax_cov is already defined
    # Add regularization
    x_reg_alpha = lam_w / jnp.sqrt(jnp.sum(x_weights))
    x_I = jnp.eye(x_nc * cat)
    x_c += x_reg_alpha * x_I
    # Compute inverse
    x_c_inv = jnp.linalg.inv(x_c)

    if pcc:
        # Partial correlation coefficient
        x_c_inv_diag = jnp.diag(x_c_inv)
        x_w = x_c_inv / jnp.sqrt(x_c_inv_diag[None, :] * x_c_inv_diag[:, None])
    elif rm_diag:
        # Zero-out diagonal
        x_w = x_c_inv / jnp.diag(x_c_inv) - x_I
        x_w = (x_w + x_w.T) / 2.0
    else:
        x_w = x_c_inv

    x_w = -jnp.reshape(x_w, (x_nc, cat, x_nc, cat))
    return x_w

def categorical_crossentropy(y_true, y_pred):
    epsilon = 1e-8
    y_pred = jnp.clip(y_pred, epsilon, 1. - epsilon)
    return -jnp.sum(y_true * jnp.log(y_pred), axis=-1)


def reg_LH(w, power_iter=True):
    ''' Penalize the largest eigenvalue, to make a low-pass filter '''
    raw = jnp.sqrt(jnp.sum(jnp.square(w), (1, 3)) + 1e-8)

    def power_iteration():
        ''' Compute the dominant eigenvalue using power iteration '''
        x = jnp.sum(raw, 0)
        dominant_eig = jnp.einsum('i,ij,j->', x, raw, x) / (1e-8 + jnp.sum(jnp.square(x)))
        return jnp.square(dominant_eig) / 2.0

    def direct_eigenvalue():
        ''' Directly compute the largest eigenvalue '''
        dominant_eig = jnp.linalg.eigvalsh(raw)[-1]
        return jnp.square(dominant_eig) / 2.0

    # Use jax.lax.cond to select the computation method
    result = jax.lax.cond(power_iter,
                          lambda _: power_iteration(),
                          lambda _: direct_eigenvalue(),
                          operand=None)
    return result


def compute_loss(params, msa, msa_weights, neff, n_total, reg_mode, lambda_L2, lambda_LH, lambda_LB, power_iter):
    states = msa.shape[2]
    ncol = msa.shape[1]
    neff_tmp = jnp.sum(msa_weights)

    # Parameters and masking
    w = params['w']
    mask_w = jnp.ones((ncol, ncol)) - jnp.tril(jnp.ones((ncol, ncol)), k=0)
    w = w * mask_w[:, None, :, None]
    w = (w + w.transpose((2, 3, 0, 1))) / 2.0
    w = w - jnp.mean(w, axis=(1, 3), keepdims=True)

    # Compute predictions
    msa_pred = jnp.einsum("ijk,jklm->ilm", msa, w)
    msa_pred = jax.nn.softmax(msa_pred, axis=-1)

    # Categorical crossentropy loss
    loss = -jnp.sum(msa * jnp.log(msa_pred + 1e-9), axis=-1)
    loss = jnp.sum(loss, axis=-1)
    loss = jnp.sum(loss * msa_weights) / neff_tmp

    # Regularization computation as before...
    # Assume `reg` calculation remains the same
    def compute_reg_L2(_):
        return 0.5 * lambda_L2 * jnp.sum(jnp.square(w)) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LH(_):
        dominant_eig = reg_LH(w, power_iter=power_iter)
        return 0.5 * lambda_LH * n_total * states * dominant_eig / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LB(_):
        raw = jnp.sqrt(jnp.sum(jnp.square(w), [1, 3]) + 1e-8)
        return lambda_LB * jnp.sum(raw) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)

    reg_w = jax.lax.switch(reg_mode, [compute_reg_L2, compute_reg_LH, compute_reg_LB], None)
    reg = reg_w
    total_loss = loss + reg  # Assume `reg` is calculated similarly

    return total_loss, reg


def compute_reg(w, neff, n_total, reg_mode, lambda_L2, lambda_LH, lambda_LB, power_iter):
    states = w.shape[1]
    def compute_reg_L2(_):
        return 0.5 * lambda_L2 * jnp.sum(jnp.square(w)) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LH(_):
        dominant_eig = reg_LH(w, power_iter=power_iter)
        return 0.5 * lambda_LH * n_total * states * dominant_eig / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LB(_):
        raw = jnp.sqrt(jnp.sum(jnp.square(w), [1, 3]) + 1e-8)
        return lambda_LB * jnp.sum(raw) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)
    reg = jax.lax.switch(reg_mode, [compute_reg_L2, compute_reg_LH, compute_reg_LB], None)
    return reg


def compute_loss_bias(params, msa, msa_weights, neff, n_total, reg_mode, lambda_L2, lambda_LH, lambda_LB, power_iter,
    field_penalty_floor=FIELD_PENALTY_FLOOR_PINNED):
    states = msa.shape[2]
    ncol = msa.shape[1]
    neff_tmp = jnp.sum(msa_weights)

    # Parameters and masking
    w = params['w']
    mask_w = jnp.ones((ncol, ncol)) - jnp.tril(jnp.ones((ncol, ncol)), k=0)
    w = w * mask_w[:, None, :, None]
    w = (w + w.transpose((2, 3, 0, 1))) / 2.0
    w = w - jnp.mean(w, axis=(1, 3), keepdims=True)

    # Compute predictions
    msa_pred = jnp.einsum("ijk,jklm->ilm", msa, w)
    msa_pred += params['b']
    msa_pred = jax.nn.softmax(msa_pred, axis=-1)

    # Categorical crossentropy loss
    loss = -jnp.sum(msa * jnp.log(msa_pred + 1e-9), axis=-1)
    loss = jnp.sum(loss, axis=-1)
    loss = jnp.sum(loss * msa_weights) / neff_tmp

    # Assume `reg` calculation remains the same
    def compute_reg_L2(_):
        return 0.5 * lambda_L2 * jnp.sum(jnp.square(w)) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LH(_):
        dominant_eig = reg_LH(w, power_iter=power_iter)
        return 0.5 * lambda_LH * n_total * states * dominant_eig / jnp.sqrt(neff) / jnp.sqrt(1000)
    def compute_reg_LB(_):
        raw = jnp.sqrt(jnp.sum(jnp.square(w), (1, 3)) + 1e-8)
        return lambda_LB * jnp.sum(raw) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)

    reg_w = jax.lax.switch(reg_mode, [compute_reg_L2, compute_reg_LH, compute_reg_LB], None)
    reg_b = 0.5 * lambda_L2 * jnp.sum(jnp.square(params['b'])) * n_total * states // jnp.sqrt(neff) / jnp.sqrt(1000)
    if not field_penalty_floor:
        # D2 (SCIENTIFIC_TRACEABILITY.md §3): ordinary division, matching the sibling terms.
        reg_b = 0.5 * lambda_L2 * jnp.sum(jnp.square(params['b'])) * n_total * states / jnp.sqrt(neff) / jnp.sqrt(1000)
    reg = reg_w + reg_b

    total_loss = loss + reg

    return total_loss, reg


def get_H(msa,states=21):
  '''get entropy by given msa'''
  nrow = msa.shape[0] # number of sequences
  ncol = msa.shape[1] # number of positions

  # compute freq per position
  pssm = np.zeros((msa.shape[1],states))
  for i in range(states):
    idx, counts = np.unique(np.where(msa == i)[1],return_counts=True)
    pssm[idx,i] = counts/msa.shape[0]

  H = -np.sum(pssm * np.log(pssm+1e-9),1)/np.log(states)
  return H


def custom_adam(lr=1.0, b1=0.9, b2=0.999, eps=1e-8, b_fix=False):
    def init_fn(params):
        mt = tree_util.tree_map(jnp.zeros_like, params)
        vt = tree_util.tree_map(jnp.zeros_like, params)
        t = 0
        return mt, vt, t

    def update_fn(updates, state, params=None):
        mt, vt, t = state

        mt_flat, mt_treedef = tree_util.tree_flatten(mt)
        vt_flat, vt_treedef = tree_util.tree_flatten(vt)
        updates_flat, updates_treedef = tree_util.tree_flatten(updates)

        new_mt_flat = []
        new_vt_flat = []
        updated_flat = []

        for grad, m, v in zip(updates_flat, mt_flat, vt_flat):
            m = b1 * m + (1 - b1) * grad
            v = b2 * v + (1 - b2) * jnp.sum(jnp.square(grad))
            new_mt_flat.append(m)
            new_vt_flat.append(v)

            if b_fix:
                m_hat = m / (1 - b1 ** (t + 1))
                v_hat = v / (1 - b2 ** (t + 1))
            else:
                m_hat = m
                v_hat = v

            update_scale = lr / (jnp.sqrt(v_hat) + eps)
            updated_flat.append(-update_scale * m_hat)

        new_mt = tree_util.tree_unflatten(mt_treedef, new_mt_flat)
        new_vt = tree_util.tree_unflatten(vt_treedef, new_vt_flat)
        updates = tree_util.tree_unflatten(updates_treedef, updated_flat)

        new_t = t + 1 if b_fix else t
        new_state = (new_mt, new_vt, new_t)
        return updates, new_state

    return optax.GradientTransformation(init_fn, update_fn)


# ── cell 13: the GREMLIN fitting entry point ─────────────────────────────────


def GREMLIN(msa,
            msa_weights=None,
            lambda_L2=0.01,
            opt_iter=400,
            batch_size=100,
            lr = 1.0,
            ignore_gap = False,
            use_bias = True,
            reg_mode = "L2",
            lambda_LH = 0.1,
            lambda_LB = 0.005,
            Inv_init = True,
            verbose = False,
            return_raw = True,
            power_iter = True,
            monitering = False,
            param_flag = False,
            gap_plane_index=GAP_PLANE_PINNED, field_penalty_floor=FIELD_PENALTY_FLOOR_PINNED):
    '''msa，a 2D np array, mas_weights, weighted sequence to downweights phylogeny effects
        looks like add msa_weights will increase the performance a little bit,same with using bias
    '''
    def initialize_bias(msa, msa_weights, neff):
        pc = 0.01 * jnp.log(neff)
        b_ini = jnp.log(jnp.sum(msa.transpose((1, 0, 2)) * msa_weights[None, :, None], axis=1) + pc)
        b_ini = b_ini - jnp.mean(b_ini, axis=-1, keepdims=True)
        return b_ini

    def initialize_weights(ncol, states, inv_init, msa, msa_weights):
        if inv_init:
            Inv = jax_inv_cov(msa, msa_weights)
        else:
            Inv = jnp.zeros((ncol, states, ncol, states))
        return Inv

    def symmetrize_and_normalize(w):
        one = jnp.ones((ncol, ncol))
        one = one - jnp.tril(one)
        w = w * one[:, None, :, None]
        w = (w + jnp.transpose(w, (2, 3, 0, 1))) / 2.0
        w = w - jnp.mean(w, (1, 3), keepdims=True)
        return w

    reg_mode_dict = {"L2": 0, "LH": 1, "LB": 2}
    reg_mode_num = reg_mode_dict[reg_mode]

    if ignore_gap: states = 20
    else: states = 21
    if use_bias:
        loss_fn = functools.partial(compute_loss_bias, field_penalty_floor=field_penalty_floor)
    else:
        loss_fn = compute_loss


    msa = jax.nn.one_hot(msa, num_classes=states)
    nrow, ncol, _ = msa.shape
    msa_weights = jax_weights(msa, gap_plane_index=gap_plane_index)
    neff = jnp.sum(msa_weights)

    if use_bias:
        params = {
            'w': initialize_weights(ncol, states, Inv_init, msa, msa_weights),
            'b': initialize_bias(msa, msa_weights, neff),
        }
    else:
        params = {
            'w': initialize_weights(ncol, states, Inv_init, msa, msa_weights),
        }

    if monitering:
        performance = []

    optimizer = custom_adam(lr=lr, b1=0.9, b2=0.999, eps=1e-8, b_fix=False)
    opt_state = optimizer.init(params)

    def reg_fn(w):
        reg = compute_reg(w, neff, ncol, reg_mode_num, lambda_L2, lambda_LH, lambda_LB, power_iter)
        return reg

    loss_fn = jax.jit(loss_fn)
    reg_fn = jax.jit(reg_fn)

    def get_gradient(params):
        def calculate_M(w):
            return jnp.sqrt(jnp.sum(jnp.square(w)) + 1e-8)
        new_w = symmetrize_and_normalize(params['w'])
        g = jax.grad(reg_fn)(new_w)
        g_m = jax.vmap(jax.vmap(jax.grad(calculate_M), in_axes=0, out_axes=0), in_axes=2, out_axes=2)(new_w)
        g_bob = g/(g_m)
        return jnp.mean(g_bob, [1, 3])

    for i in range(opt_iter):
        if verbose and (i+1) % int(opt_iter/5) == 0:
            loss, reg = loss_fn(params, msa, msa_weights, neff, ncol, reg_mode_num, lambda_L2, lambda_LH, lambda_LB, power_iter)
            print("iter full_loss,regularizer", i+1, loss, reg)

        idx = np.random.choice(nrow, size=batch_size, replace=False)
        batch_msa = msa[idx]
        batch_msa_weights = msa_weights[idx]

        _, grads = jax.value_and_grad(loss_fn, has_aux=True)(params, batch_msa, batch_msa_weights, neff, ncol, reg_mode_num, lambda_L2, lambda_LH, lambda_LB, power_iter)
        updates, opt_state = optimizer.update(grads, opt_state, params)
        params = optax.apply_updates(params, updates)


        if monitering:

            raw_apc = jax_apc(symmetrize_and_normalize(params['w']), return_raw=return_raw)
            gradient_M =  get_gradient(params)
            performance.append([i, *raw_apc, gradient_M])

    if monitering:
        return performance
    raw_apc = jax_apc(symmetrize_and_normalize(params['w']), return_raw=return_raw)

    if use_bias:
        V = params['b']
    else:
        V = np.zeros((ncol, states))
    W = symmetrize_and_normalize(params['w'])

    if not param_flag:
        return raw_apc
    else:
        return V, W


# ── cell 14: Hamiltonian and pseudo-likelihood observables ───────────────────


def get_Hamiltonian_loss(msa, w, b=None, return_H=False):

    # einsum to compute the VW
    VW = jnp.einsum("njk,jklm->nlm", msa, w)
    if b is not None:
        VW += b

    # hamiltonian
    H = -jnp.sum(msa * VW, axis=(1, 2))
    msa_pred = jax.nn.softmax(VW, axis=-1)

    # Categorical Cross Entropy loss
    loss = jnp.sum(-jnp.sum(msa * jnp.log(msa_pred + 1e-8), axis=-1), axis=-1)

    if return_H:
        return H
    else:
        return loss

def get_Hamiltonian(msa, w, b=None):

    # einsum to compute the VW
    VW = jnp.einsum("njk,jklm->nlm", msa, w)
    if b is not None:
        VW += b

    msa_pred = jax.nn.softmax(VW, axis=-1)
    return msa_pred


# ── faithfulness guard ───────────────────────────────────────────────────────


def _pinned_source(func: Callable) -> str:
    """Render a transcription back to its pinned form.

    Only the correction parameters (ours, with the pinned behaviour as default)
    are removed; every other line must match the notebook exactly, so any drift
    in the body - or in the notebook pin - fails the guard below.
    """
    lines: list[str] = []
    dropping_correction = False
    for line in inspect.getsource(func).splitlines():
        if line.strip().startswith("if not field_penalty_floor:"):
            # Drop the D2 guard block, including its comment and the corrected
            # assignment; the pinned (default) assignment above stays.
            dropping_correction = True
            continue
        if dropping_correction:
            if "reg_b =" in line:
                dropping_correction = False
            continue
        lines.append(line)
    text = "\n".join(lines)
    for old, new in _PINNED_RENDERING:
        text = text.replace(old, new)
    return text


#: Exact replacements that turn the transcription back into the pinned text.
#: ``gap_plane_index`` and the D2 guard are ours, so their parameters are
#: stripped; the two multi-line entries collapse the longer signatures back to
#: the notebook's single-line form.
_PINNED_RENDERING = (
    (", gap_plane_index=gap_plane_index", ""),
    (", gap_plane_index=GAP_PLANE_PINNED", ""),
    (",\n    field_penalty_floor=FIELD_PENALTY_FLOOR_PINNED):", "):"),
    (",\n            gap_plane_index=GAP_PLANE_PINNED, field_penalty_floor=FIELD_PENALTY_FLOOR_PINNED):", "):"),
    ("functools.partial(compute_loss_bias, field_penalty_floor=field_penalty_floor)", "compute_loss_bias"),
    ("gap_plane_index", "-1"),
)


def _normalize(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def assert_matches_pinned_notebook(cells: list[str]) -> None:
    """Refuse unless every transcription is the pinned notebook's own source.

    ``cells`` is the pinned notebook's per-cell source.  Each transcribed
    function, rendered back to its pinned form, must appear verbatim in its
    cell (normalized for leading/trailing whitespace and blank lines), and the
    ``alphabet`` literal must appear in cell 7.
    """
    cell_text = {index: _normalize(source) for index, source in enumerate(cells)}
    for index, names in TRANSCRIBED.items():
        if index not in cell_text:
            raise SystemExit(f"pinned notebook has no cell {index} to check the transcription against")
        for name in names:
            rendered = _normalize(_pinned_source(globals()[name]))
            if rendered not in cell_text[index]:
                raise SystemExit(
                    f"transcription of {name!r} is not the pinned notebook cell {index}; "
                    "the notebook pin or the transcription drifted - re-audit before regenerating"
                )
    if _normalize(f'alphabet =  "{alphabet}"') not in cell_text[CELL_UTILS]:
        # The pinned cell writes two spaces around the ``=``; ``_normalize``
        # strips only the two ends of each line, so the interior spacing matters.
        raise SystemExit("transcribed `alphabet` literal is not the pinned notebook cell 7")
