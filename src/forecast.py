"""Workload forecasters and accuracy metrics for the IA autoscaler.

Each forecaster is a callable f(history, h) -> predicted request rate h minutes after the last observation.
Dependency-light: NumPy only.
"""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np

LAGS = 6  # lag window for the learned autoregressive model

def naive(history, h): return history[-1]

def moving_average(history, h, window=5):
    w=history[-window:]; return sum(w)/len(w)

def holt(history, h, alpha=.5, beta=.3):
    """Holt's linear exponential smoothing: level + h * trend."""
    level, trend = history[0], 0.
    for x in history[1:]:
        prev=level; level=alpha*x+(1-alpha)*(level+trend); trend=beta*(level-prev)+(1-beta)*trend
    return level+h*trend

def window_trend(history, h, window=8):
    """Least-squares line over the last `window` minutes, extrapolated h minutes."""
    w=np.asarray(history[-window:],dtype=float)
    if len(w)<3: return float(w[-1])
    slope,intercept=np.polyfit(np.arange(len(w)),w,1); return float(intercept+slope*(len(w)-1+h))

class RidgeAR:
    """Learned model: ridge regression on the last LAGS observations (+ their deltas), one model per horizon."""
    def __init__(self, lags=LAGS, l2=1.0): self.lags=lags; self.l2=l2; self.w={}
    def _x(self, window):
        w=np.asarray(window,dtype=float); return np.concatenate([[1.],w,np.diff(w)])
    def fit(self, loads, horizons=(1,3,5)):
        for h in horizons:
            X=[];y=[]
            for load in loads:
                for t in range(self.lags-1,len(load)-h): X.append(self._x(load[t-self.lags+1:t+1])); y.append(load[t+h])
            X=np.asarray(X); y=np.asarray(y); A=X.T@X+self.l2*np.eye(X.shape[1]); A[0,0]-=self.l2
            self.w[h]=np.linalg.solve(A,X.T@y)
        return self
    def __call__(self, history, h):
        if len(history)<self.lags: return history[-1]
        hh=h if h in self.w else min(self.w,key=lambda k:abs(k-h))
        return float(self._x(history[-self.lags:])@self.w[hh])

def make_forecasters(train_loads):
    """Baselines plus the learned ridge-AR model fitted only on train_loads."""
    return {'naive':naive,'moving_avg':moving_average,'holt':holt,'window_trend':window_trend,'ridge_ar':RidgeAR().fit(train_loads)}

def predictive_action(rate, fut, active, booting, capacity_rps, hi=.72, lo=.28):
    """Forecast-driven threshold rule shared by the simulator and the live controller.

    Scale out if current OR forecast utilisation is high (forecast capacity counts instances still booting);
    scale in only if both are low. Returns -1, 0 or +1."""
    now_util=rate/(max(1,active)*capacity_rps); fut_util=max(fut,0.)/(max(1,active+booting)*capacity_rps)
    if fut_util>hi or now_util>hi: return 1
    if fut_util<lo and now_util<lo and active>1: return -1
    return 0

def forecast_with_error(pred, t, error, rng):
    """Inject controlled forecast error: relative bias, Gaussian noise (rps), or a window where the forecast is overridden."""
    if not error: return pred
    ov=error.get('override')
    if ov and ov[0]<=t<ov[1]: return ov[2]
    return max(0.,pred*(1+error.get('bias',0.))+rng.gauss(0,error.get('noise',0.)))

def accuracy(forecaster, load, h, warmup=LAGS):
    """MAE, RMSE, MAPE of forecasting load[t+h] from load[:t+1]."""
    errs=[];pct=[]
    for t in range(warmup,len(load)-h):
        a=load[t+h]; e=forecaster(load[:t+1],h)-a; errs.append(e); pct.append(abs(e)/max(a,1.))
    errs=np.asarray(errs)
    return dict(mae=float(np.abs(errs).mean()),rmse=float(math.sqrt((errs**2).mean())),mape_pct=100*float(np.mean(pct)))

if __name__=='__main__':
    from experiment import trace, training_set
    train=[l for sd in (1,2,3) for l in training_set(sd)]
    fcs=make_forecasters(train)
    tests={'daily (seen kind)':trace('daily',seed=99),'ramp (seen kind)':trace('ramp',seed=99),'noise (seen kind)':trace('noise',seed=99),
           'spike (held-out)':trace('spike',seed=99),'step (held-out)':trace('step',seed=99)}
    out=[]
    for tname,load in tests.items():
        for fname,f in fcs.items():
            for h in (1,3,5): out.append(dict(trace=tname,forecaster=fname,horizon_min=h,**accuracy(f,load,h)))
    res=Path('results'); res.mkdir(exist_ok=True); (res/'forecast_metrics.json').write_text(json.dumps(out,indent=2))
    print(f"{'trace':20}{'forecaster':14}{'h':>3}{'MAE':>8}{'RMSE':>8}{'MAPE%':>8}")
    for r in out:
        if r['horizon_min']==3: print(f"{r['trace']:20}{r['forecaster']:14}{r['horizon_min']:>3}{r['mae']:8.2f}{r['rmse']:8.2f}{r['mape_pct']:8.1f}")
