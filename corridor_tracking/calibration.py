"""Surveyed 3D correspondences: robust rigid fit and independent validation."""
from __future__ import annotations

import numpy as np


def rigid_fit(camera,target):
    a,b=np.asarray(camera,dtype=float),np.asarray(target,dtype=float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or len(a)<3 or not np.isfinite([a,b]).all():
        raise ValueError('Need at least three finite 3D correspondences')
    ac,bc=a-a.mean(axis=0),b-b.mean(axis=0)
    if np.linalg.matrix_rank(ac,tol=1e-6)<2 or np.linalg.matrix_rank(bc,tol=1e-6)<2:
        raise ValueError('Collinear points cannot determine 3D orientation; add lateral/height points')
    U,_,Vt=np.linalg.svd(ac.T@bc)
    correction=np.eye(3);correction[-1,-1]=np.linalg.det(Vt.T@U.T)
    R=Vt.T@correction@U.T
    t=b.mean(axis=0)-R@a.mean(axis=0)
    M=np.eye(4);M[:3,:3]=R;M[:3,3]=t
    return M


def apply_transform(points,matrix):
    return np.asarray(points)@matrix[:3,:3].T+matrix[:3,3]


def robust_fit(camera,target,threshold=.12,seed=20261104):
    a,b=np.asarray(camera,dtype=float),np.asarray(target,dtype=float)
    rigid_fit(a,b) # validate global geometry before RANSAC
    if not np.isfinite(threshold) or threshold<=0:
        raise ValueError('RANSAC threshold must be positive')
    rng=np.random.default_rng(seed);best=None;best_score=(-1,-float('inf'))
    for _ in range(300):
        sample=rng.choice(len(a),3,replace=False)
        try:
            m=rigid_fit(a[sample],b[sample])
        except ValueError:
            continue
        errors=np.linalg.norm(apply_transform(a,m)-b,axis=1)
        mask=errors<=threshold
        score=(int(mask.sum()),-float(errors[mask].sum()))
        if score>best_score:
            best,best_score=mask,score
    if best is None or best.sum()<max(3,int(np.ceil(len(a)*.6))):
        raise ValueError('Fewer than 60% mutually consistent calibration points')
    m=rigid_fit(a[best],b[best])
    residual=np.linalg.norm(apply_transform(a,m)-b,axis=1)
    return m,residual<=threshold


def errors(predicted,target):
    residual=np.asarray(predicted)-np.asarray(target)
    if not len(residual):
        return dict(count=0,status='not_evaluated')
    norm=np.linalg.norm(residual,axis=1)
    return dict(count=len(norm),bias_xyz_m=residual.mean(axis=0).tolist(),
                mae_xyz_m=np.abs(residual).mean(axis=0).tolist(),
                rmse_xyz_m=np.sqrt(np.mean(residual**2,axis=0)).tolist(),
                euclidean_mae_m=float(norm.mean()),euclidean_rmse_m=float(np.sqrt(np.mean(norm**2))),
                euclidean_p95_m=float(np.percentile(norm,95)),status='evaluated')


def evaluate_groups(predicted,target):
    p,t=np.asarray(predicted),np.asarray(target)
    result={'all':errors(p,t)}
    if not len(t):
        return result
    for label,mask in [('X_lt_5',t[:,0]<5),('X_5_to_10',(t[:,0]>=5)&(t[:,0]<10)),('X_ge_10',t[:,0]>=10),
                       ('Z_lt_05',t[:,2]<.5),('Z_ge_05',t[:,2]>=.5)]:
        result[label]=errors(p[mask],t[mask])
    # Actual surveyed lateral stations, not an assumed corridor centre.
    for y in np.unique(np.round(t[:,1],2)):
        mask=np.isclose(np.round(t[:,1],2),y)
        result[f'Y_{y:.2f}']=errors(p[mask],t[mask])
    return result
