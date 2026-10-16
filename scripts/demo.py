"""Narrated demo of the ia-autoscaler project, for screen recording.

Run from the project root:  python scripts/demo.py [--pause] [--rerun]
  --pause   wait for Enter between sections (easier to talk over)
  --rerun   regenerate all results first (~1 min); otherwise reads results/*.json
"""
import argparse, csv, json, subprocess, sys
from pathlib import Path

R = Path('results')
ap = argparse.ArgumentParser(); ap.add_argument('--pause', action='store_true'); ap.add_argument('--rerun', action='store_true'); args = ap.parse_args()

def head(title):
    if args.pause: input('\n[Enter to continue] ')
    print('\n' + '=' * 78 + f'\n  {title}\n' + '=' * 78)

if args.rerun:
    for cmd in (['src/forecast.py'], ['src/experiment.py'], ['src/dqn.py'], ['scripts/make_figures.py']):
        print('running', *cmd); subprocess.run([sys.executable, *cmd], stdout=subprocess.DEVNULL, check=True)

head('1. Problem: ML-based cloud resource manager (predict workload, allocate instances)')
print('AWS Auto Scaling Group, 1-6 t3.micro behind an ALB, region ap-southeast-2.\n'
      'Goal: keep p95 latency < 500 ms at low cost/energy, without scaling thrash.\n'
      'Hard part: a new instance needs 3 minutes to boot, so decisions must be made ahead of demand.')

head('2. Real AWS evidence (calibration, Oct 12) - what the simulator is built on')
by = {}
for r in csv.DictReader((R / 'calibration_client.csv').open()): by.setdefault(int(r['workers']), []).append(r)
print(f"{'workers':>8}{'RPS':>8}{'p95 ms':>9}{'failures':>10}")
for w in sorted(by):
    rs = by[w]; print(f"{w:>8}{sum(float(r['rps']) for r in rs)/len(rs):>8.2f}{sum(float(r['p95_ms']) for r in rs)/len(rs):>9.0f}{sum(int(r['failures']) for r in rs):>10}")
t = json.loads((R / 'target_tracking_load.json').read_text())
print('\nLive target-tracking test:', {k: t[k] for k in list(t)[:6]} if isinstance(t, dict) else t)
print('Calibrated: ~8 RPS per instance, 3-minute boot lag.  (AWS stack is torn down: ASG at 0, no ALB.)')

head('3. Features, algorithm, horizon')
print('Features : request rate, rate change, active + booting instances, forecast of rate at +3 min\n'
      'Forecast : ridge-regression autoregression on last 6 minutes (vs naive, moving avg, Holt, trend)\n'
      'Controller: tabular Q-learning (and a NumPy DQN); actions scale in / hold / scale out\n'
      'Horizon  : 3 minutes = boot lag.   Train and test traces are different (test spike at min 110-140).')

head('4. Prediction accuracy (held-out spike trace)')
fm = json.loads((R / 'forecast_metrics.json').read_text())
print(f"{'forecaster':<14}" + ''.join(f'{"MAPE h="+str(h):>12}' for h in (1, 3, 5)) + f"{'MAE h=3':>10}")
for f in ('naive', 'moving_avg', 'holt', 'window_trend', 'ridge_ar'):
    rs = {r['horizon_min']: r for r in fm if r['trace'] == 'spike (held-out)' and r['forecaster'] == f}
    print(f'{f:<14}' + ''.join(f"{rs[h]['mape_pct']:>11.1f}%" for h in (1, 3, 5)) + f"{rs[3]['mae']:>10.2f}")
print('-> spike onset cannot be predicted from history; error grows with horizon.')

head('5. Policy comparison: utilization, latency, cost, energy (simulated, held-out trace)')
ms = json.loads((R / 'metrics.json').read_text()) + json.loads((R / 'dqn_metrics.json').read_text())
print(f"{'policy':<26}{'inst':>6}{'util':>7}{'p95ms':>8}{'viol':>6}{'cost$':>8}{'Wh':>7}{'actions':>9}")
for m in ms:
    print(f"{m['method']:<26}{m['avg_instances']:>6.2f}{m['avg_utilization']*100:>6.0f}%{m['p95_latency_ms']:>8.0f}{m['violations']:>6}{m['cost_usd']:>8.3f}{m['energy_wh']:>7.1f}{m['scaling_actions']:>9}")
print('-> reactive: cheap but 37 actions; Q-learning: 0 violations, 4 actions, ~2x cost; DQN: unstable across seeds.')

head('6. What happens when the prediction is wrong?  (forecast-aware Q-learner)')
mis = json.loads((R / 'misprediction_metrics.json').read_text())
print(f"{'forecast error':<16}{'viol (no guard)':>17}{'viol (guardrails)':>19}{'cost no/guard':>18}")
for sc in ('accurate', 'bias_+30%', 'bias_-30%', 'noise_sd_5rps', 'missed_spike'):
    a = next(r for r in mis if r['scenario'] == sc and not r['guardrails'] and r['method'].startswith('qlearn'))
    b = next(r for r in mis if r['scenario'] == sc and r['guardrails'] and r['method'].startswith('qlearn'))
    print(f"{sc:<16}{a['violations']:>17.1f}{b['violations']:>19.1f}{'$%.3f / $%.3f' % (a['cost_usd'], b['cost_usd']):>18}")
print('-> under-prediction hurts most; guardrails (80% ceiling, 2-violation fallback) cap the damage but cost money.')

head('7. Figures and report')
for f in ('calibration_latency.png', 'forecast_vs_actual.png', 'simulated_policy_comparison.png', 'misprediction_robustness.png'):
    print(' ', R / f)
print('  docs/FINAL_REPORT.md   (full report)')

head('8. Live AWS runs of the guardrailed controller (recorded traces)')
for name in ('reactive', 'forecast'):
    f = R / f'live_demo_log_{name}.json'
    if f.exists():
        L = json.loads(f.read_text())
        print(f"{name:9} policy: peak ALB p95 {max(x['alb_p95_ms'] for x in L)} ms, ticks over 500 ms {sum(x['alb_p95_ms'] > 500 for x in L)}/{len(L)}, peak instances {max(x['desired'] for x in L)}")
print('(different load shapes: reactive = step burst, forecast = gradual ramp; single runs)')
