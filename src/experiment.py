"""Dependency-free simulator and tabular RL baseline for the IA autoscaler."""
from __future__ import annotations
import csv, json, math, random
from pathlib import Path
from forecast import make_forecasters, forecast_with_error, predictive_action

CAPACITY_RPS = 8.0       # Calibrated (Phase 2): latency knee of the t3.micro step-load test
BOOT_MINUTES = 3         # Calibrated (Phase 2): launch + health-check lag
FORECAST_HORIZON = 3     # minutes; equals BOOT_MINUTES so a forecast covers the boot lag
GUARD_UTIL, GUARD_STREAK = 0.80, 2   # mirrors src/controller.py: hard CPU ceiling, persistent-violation fallback
LATENCY_TARGET_MS = 500
INSTANCE_HOURLY_USD = 0.015
IDLE_WATTS, PEAK_WATTS = 3.0, 11.0
MIN_I, MAX_I = 1, 6

def trace(kind, n=240, seed=0, at=110):
    r = random.Random(seed); out=[]
    for t in range(n):
        x=t/n
        if kind=='daily': v=12+8*math.sin(2*math.pi*x-math.pi/2)+r.uniform(-1,1)
        elif kind=='ramp': v=4+24*x+r.uniform(-1,1)
        elif kind=='spike': v=7+(28 if at<=t<at+30 else 0)+r.uniform(-1,1)
        elif kind=='noise': v=12+r.uniform(-8,10)
        else: v=5 if t<80 else (32 if t<160 else 10)  # held-out step
        out.append(max(0.,v))
    return out

class Env:
    """Discrete-time autoscaling simulator.

    forecaster: optional callable(history, h) -> predicted rate; adds a bucketed forecast to the state.
    error: optional dict(bias, noise, override=(lo, hi, value), seed) injected into the forecast.
    guard: wrap actions in the deterministic safety guardrails (hard utilisation ceiling, violation fallback).
    """
    def __init__(self, load, forecaster=None, error=None, guard=False):
        self.load=load; self.forecaster=forecaster; self.error=error; self.guard=guard; self.reset()
    def reset(self):
        self.t=0; self.active=1; self.boot=[]; self.last=0.; self.last_util=0.; self.streak=0; self._fc={}
        self.noise_rng=random.Random((self.error or {}).get('seed',0)); return self.state()
    def forecast(self):
        """Predicted rate FORECAST_HORIZON minutes ahead, from observations up to and including the current minute."""
        t=min(self.t,len(self.load)-1)
        if t not in self._fc:
            pred=self.forecaster(self.load[:t+1],FORECAST_HORIZON)
            self._fc[t]=forecast_with_error(pred,t,self.error,self.noise_rng)
        return self._fc[t]
    def state(self):
        rate=self.load[min(self.t,len(self.load)-1)]; delta=rate-self.last
        base=(min(5,int(rate/6)), min(4,max(0,int((delta+8)/4))), self.active-1, min(3,len(self.boot)))
        return base+(min(5,int(self.forecast()/6)),) if self.forecaster else base
    def step(self, action):
        # action: -1,0,+1. Never drop below one and never exceed six.
        if self.guard and (self.last_util>=GUARD_UTIL or self.streak>=GUARD_STREAK): action=1
        if action==1 and self.active+len(self.boot)<MAX_I: self.boot.append(BOOT_MINUTES)
        if action==-1 and self.active>MIN_I: self.active-=1
        self.boot=[x-1 for x in self.boot]; ready=sum(x<=0 for x in self.boot); self.boot=[x for x in self.boot if x>0]; self.active+=ready
        rate=self.load[self.t]; capacity=max(1,self.active)*CAPACITY_RPS; util=min(1.5,rate/capacity)
        latency=60 if util<.7 else 60+440*((util-.7)/.3)**2
        dropped=max(0.,rate-capacity)
        reward=-(self.active*INSTANCE_HOURLY_USD/60)- (8 if latency>LATENCY_TARGET_MS else 0)-.25*(action!=0)-.5*dropped
        row=dict(minute=self.t,rps=rate,instances=self.active,booting=len(self.boot),utilization=util,latency_ms=latency,dropped_rps=dropped,action=action,reward=reward)
        self.last=rate; self.last_util=util; self.streak=self.streak+1 if latency>LATENCY_TARGET_MS else 0
        self.t+=1; return self.state(),reward,self.t>=len(self.load),row

def reactive(env):
    rows=[]
    while env.t<len(env.load):
        rate=env.load[env.t]; util=rate/(max(1,env.active)*CAPACITY_RPS); a=1 if util>.72 else (-1 if util<.28 and env.active>1 else 0)
        _,_,_,row=env.step(a); rows.append(row)
    return rows

def predictive_reactive(env):
    """Threshold rule on the forecast: act on the predicted rate instead of waiting for utilisation to react."""
    rows=[]
    while env.t<len(env.load):
        a=predictive_action(env.load[env.t],env.forecast(),env.active,len(env.boot),CAPACITY_RPS)
        _,_,_,row=env.step(a); rows.append(row)
    return rows

TT_TARGET, TT_SCALE_IN_MINUTES = 0.60, 15   # AWS target tracking: 60% target utilisation; scale-in only after 15 consecutive low minutes

def target_tracking(env):
    """Model of AWS ASG target tracking on average utilisation.

    desired = ceil(in-service * util / target). Scale-out is immediate (instances still booting count as already requested);
    scale-in is conservative: only after TT_SCALE_IN_MINUTES consecutive minutes where the metric implies fewer instances.
    The simulator moves at most one instance per minute."""
    rows=[]; low=0
    while env.t<len(env.load):
        util=env.load[env.t]/(max(1,env.active)*CAPACITY_RPS); desired=math.ceil(env.active*util/TT_TARGET)
        low=low+1 if desired<env.active else 0; a=0
        if desired>env.active+len(env.boot): a=1
        elif low>=TT_SCALE_IN_MINUTES: a=-1; low=0
        _,_,_,row=env.step(a); rows.append(row)
    return rows

def training_set(seed):
    """Training traces (cycled per episode). The held-out test is trace('spike', seed=99) with its spike at minutes 110-140:
    training spikes occur at other times, and the 'step' trace is never trained on."""
    return [trace('daily',seed=seed),trace('ramp',seed=seed),trace('noise',seed=seed),trace('spike',seed=seed,at=50),trace('spike',seed=seed,at=165)]

def qlearn(train_loads, seed=0, episodes=180, **env_kw):
    """Tabular Q-learning; episodes cycle through train_loads. Returns the Q-table and per-episode reward."""
    q={}; r=random.Random(seed); curve=[]
    for ep in range(episodes):
        e=Env(train_loads[ep%len(train_loads)],**env_kw); s=e.reset(); total=0.; eps=max(.04,.35*(1-ep/episodes))
        while e.t<len(e.load):
            values=q.setdefault(s,[0.,0.,0.]); a=r.choice([-1,0,1]) if r.random()<eps else [-1,0,1][max(range(3),key=lambda i:values[i])]
            ns,reward,done,_=e.step(a); nv=q.setdefault(ns,[0.,0.,0.]); values[a+1]+=.15*(reward+.95*max(nv)-values[a+1]); s=ns; total+=reward
        curve.append(total)
    return q,curve

def run_q(q, load, **env_kw):
    """Greedy rollout of a learned Q-table on a trace (unseen states hold)."""
    e=Env(load,**env_kw); rows=[]
    while e.t<len(load):
        s=e.state(); a=[-1,0,1][max(range(3),key=lambda i:q.get(s,[0,0,0])[i])]; _,_,_,row=e.step(a); rows.append(row)
    return rows

def summary(name, rows):
    return dict(method=name,avg_instances=sum(x['instances'] for x in rows)/len(rows),avg_utilization=sum(x['utilization'] for x in rows)/len(rows),p95_latency_ms=sorted(x['latency_ms'] for x in rows)[int(.95*len(rows))-1],violations=sum(x['latency_ms']>LATENCY_TARGET_MS for x in rows),cost_usd=sum(x['instances'] for x in rows)*INSTANCE_HOURLY_USD/60,energy_wh=sum((IDLE_WATTS+(PEAK_WATTS-IDLE_WATTS)*min(1,x['utilization']))/60 for x in rows),scaling_actions=sum(x['action']!=0 for x in rows))

SEEDS=(1,2,3)
MISPREDICTION_SCENARIOS={
    'accurate':None,
    'bias_+30%':dict(bias=.30,seed=7),
    'bias_-30%':dict(bias=-.30,seed=7),
    'noise_sd_5rps':dict(noise=5.,seed=7),
    'missed_spike':dict(override=(105,140,7.0),seed=7),   # forecast says "no spike" while a 35 rps spike arrives
}

def mean_of(rows_list, name):
    keys=[k for k in rows_list[0] if k!='method']
    return dict(method=name,**{k:sum(r[k] for r in rows_list)/len(rows_list) for k in keys})

if __name__=='__main__':
    out=Path('results'); out.mkdir(exist_ok=True); test=trace('spike',seed=99)
    ridge=make_forecasters([l for sd in SEEDS for l in training_set(sd)])['ridge_ar']
    records=[summary('reactive',reactive(Env(test))), summary('target_tracking',target_tracking(Env(test))), summary('predictive_reactive',predictive_reactive(Env(test,forecaster=ridge)))]
    curves=[]; qs={}; qfs={}
    for seed in SEEDS:
        train=training_set(seed)                # independent training traces per seed; evaluated on the held-out spike trace
        qs[seed],curve=qlearn(train,seed); records.append(summary(f'qlearn_seed_{seed}',run_q(qs[seed],test)))
        curves += [dict(seed=seed,episode=i,reward=v,agent='qlearn') for i,v in enumerate(curve)]
        qfs[seed],curve=qlearn(train,seed,forecaster=ridge); records.append(summary(f'qlearn_forecast_seed_{seed}',run_q(qfs[seed],test,forecaster=ridge)))
        curves += [dict(seed=seed,episode=i,reward=v,agent='qlearn_forecast') for i,v in enumerate(curve)]
    with open(out/'metrics.json','w') as f: json.dump(records,f,indent=2)
    with open(out/'learning_curves.csv','w',newline='') as f: w=csv.DictWriter(f,fieldnames=['agent','seed','episode','reward']); w.writeheader(); w.writerows(curves)
    # What happens when the prediction is wrong: inject forecast error, with and without the deterministic guardrails.
    mis=[]
    for scen,err in MISPREDICTION_SCENARIOS.items():
        for guard in (False,True):
            tag='guarded' if guard else 'unguarded'
            mis.append(dict(scenario=scen,guardrails=guard,**summary('predictive_reactive',predictive_reactive(Env(test,forecaster=ridge,error=err,guard=guard)))))
            mis.append(dict(scenario=scen,guardrails=guard,**mean_of([summary('',run_q(qfs[s],test,forecaster=ridge,error=err,guard=guard)) for s in SEEDS],'qlearn_forecast(mean of 3 seeds)')))
    mis.append(dict(scenario='no_forecast',guardrails=False,**summary('target_tracking',target_tracking(Env(test)))))
    mis.append(dict(scenario='no_forecast',guardrails=False,**summary('reactive',reactive(Env(test)))))
    mis.append(dict(scenario='no_forecast',guardrails=True,**summary('target_tracking',target_tracking(Env(test,guard=True)))))
    mis.append(dict(scenario='no_forecast',guardrails=True,**summary('reactive',reactive(Env(test,guard=True)))))
    (out/'misprediction_metrics.json').write_text(json.dumps(mis,indent=2))
    for r in records: print(f"{r['method']:26} inst={r['avg_instances']:.2f} p95={r['p95_latency_ms']:7.1f} viol={r['violations']:3d} cost=${r['cost_usd']:.3f} E={r['energy_wh']:.2f}Wh actions={r['scaling_actions']}")
    print()
    for r in mis: print(f"{r['scenario']:14} guard={str(r['guardrails']):5} {r['method']:34} viol={r['violations']:5.1f} cost=${r['cost_usd']:.3f} E={r['energy_wh']:.2f} actions={r['scaling_actions']:.1f}")
