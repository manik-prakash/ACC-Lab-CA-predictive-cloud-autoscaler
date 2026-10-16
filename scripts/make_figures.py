"""Create report figures from measured calibration and simulator artifacts."""
import csv, json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

out=Path('results'); out.mkdir(exist_ok=True)
rows=list(csv.DictReader((out/'calibration_client.csv').open()))
by={}
for r in rows:
    by.setdefault(int(r['workers']),[]).append(r)
x=sorted(by)
rps=[sum(float(r['rps']) for r in by[k])/len(by[k]) for k in x]
p95=[sum(float(r['p95_ms']) for r in by[k])/len(by[k]) for k in x]
plt.figure(figsize=(7,4)); plt.plot(rps,p95,'o-',label='client p95'); plt.axhline(500,color='crimson',ls='--',label='500 ms target'); plt.xlabel('Throughput (requests/s)'); plt.ylabel('p95 latency (ms)'); plt.legend(); plt.tight_layout(); plt.savefig(out/'calibration_latency.png',dpi=160); plt.close()
metrics=json.loads((out/'metrics.json').read_text())+json.loads((out/'dqn_metrics.json').read_text())
names=[m['method'] for m in metrics]; costs=[m['cost_usd'] for m in metrics]; violations=[m['violations'] for m in metrics]
fig,ax=plt.subplots(1,2,figsize=(10,4)); ax[0].bar(range(len(names)),costs); ax[0].set_xticks(range(len(names)),names,rotation=45,ha='right'); ax[0].set_ylabel('Simulated cost (USD)'); ax[1].bar(range(len(names)),violations); ax[1].set_xticks(range(len(names)),names,rotation=45,ha='right'); ax[1].set_ylabel('Latency-violation minutes'); fig.tight_layout(); fig.savefig(out/'simulated_policy_comparison.png',dpi=160); plt.close(fig)

# Forecast vs actual on the held-out spike trace (3-minute horizon) and forecast-error robustness.
import sys
sys.path.insert(0,'src')
from experiment import trace, training_set, make_forecasters, FORECAST_HORIZON
fcs=make_forecasters([l for sd in (1,2,3) for l in training_set(sd)]); load=trace('spike',seed=99); h=FORECAST_HORIZON
plt.figure(figsize=(9,4)); plt.plot(range(len(load)),load,color='black',lw=1.5,label='actual rps')
for name in ('naive','holt','ridge_ar'):
    plt.plot(range(h,len(load)),[fcs[name](load[:t+1],h) for t in range(len(load)-h)],lw=1,label=f'{name} (forecast made {h} min earlier)')
plt.xlabel('Minute'); plt.ylabel('Requests/s'); plt.legend(fontsize=8); plt.tight_layout(); plt.savefig(out/'forecast_vs_actual.png',dpi=160); plt.close()
mis=json.loads((out/'misprediction_metrics.json').read_text())
scen=[]; [scen.append(r['scenario']) for r in mis if r['scenario'] not in scen and r['scenario']!='no_forecast']
fig,ax=plt.subplots(1,2,figsize=(11,4),sharey=True)
for a,policy in zip(ax,('predictive_reactive','qlearn_forecast(mean of 3 seeds)')):
    for k,(guard,label) in enumerate(((False,'no guardrails'),(True,'with guardrails'))):
        vals=[next(r['violations'] for r in mis if r['scenario']==s and r['guardrails']==guard and r['method']==policy) for s in scen]
        a.bar([i+.4*k for i in range(len(scen))],vals,width=.4,label=label)
    a.set_xticks([i+.2 for i in range(len(scen))],scen,rotation=30,ha='right'); a.set_title(policy.split('(')[0]); a.legend(fontsize=8)
ax[0].set_ylabel('SLO-violation minutes (held-out spike trace)'); fig.tight_layout(); fig.savefig(out/'misprediction_robustness.png',dpi=160); plt.close(fig)
