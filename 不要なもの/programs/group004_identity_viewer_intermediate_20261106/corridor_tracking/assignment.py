"""Rectangular minimum-cost one-to-one assignment without a SciPy binary dependency."""
import numpy as np


def linear_sum_assignment(cost):
    a = np.asarray(cost,dtype=float)
    if a.ndim!=2 or not np.isfinite(a).all():
        raise ValueError('Assignment costs must be a finite matrix')
    if min(a.shape)==0:
        return np.array([],dtype=int),np.array([],dtype=int)
    transposed = a.shape[0]>a.shape[1]
    if transposed:
        a=a.T
    n,m=a.shape
    u,v=np.zeros(n+1),np.zeros(m+1)
    p,way=np.zeros(m+1,dtype=int),np.zeros(m+1,dtype=int)
    for i in range(1,n+1):
        p[0]=i;j0=0
        minimum=np.full(m+1,np.inf);used=np.zeros(m+1,dtype=bool)
        while True:
            used[j0]=True;i0=p[j0];delta=np.inf;j1=0
            for j in range(1,m+1):
                if used[j]:
                    continue
                current=a[i0-1,j-1]-u[i0]-v[j]
                if current<minimum[j]:
                    minimum[j]=current;way[j]=j0
                if minimum[j]<delta:
                    delta=minimum[j];j1=j
            for j in range(m+1):
                if used[j]:
                    u[p[j]]+=delta;v[j]-=delta
                else:
                    minimum[j]-=delta
            j0=j1
            if p[j0]==0:
                break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if j0==0:
                break
    pairs=sorted((p[j]-1,j-1) for j in range(1,m+1) if p[j])
    if transposed:
        pairs=sorted((j,i) for i,j in pairs)
    return np.array([i for i,j in pairs]),np.array([j for i,j in pairs])
