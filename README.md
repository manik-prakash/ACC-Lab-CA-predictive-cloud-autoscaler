# Predictive Cloud Autoscaler

An ML-based cloud resource manager for the Advanced Cloud Computing lab CA ("Cloud Resource Management"). It forecasts workload and decides how many AWS EC2 instances an Auto Scaling Group should run, then evaluates the result on prediction accuracy, utilization, latency, cost and energy, including what happens when the forecast is wrong.

The ASG is only the actuator. The project replaces its decision policy with:

- a **workload forecaster** (ridge-regression autoregression, 3-minute horizon = instance boot lag),
- **reinforcement-learning controllers** (tabular Q-learning, NumPy DQN) trained in a simulator calibrated from real AWS measurements,
- **deterministic guardrails** (80% CPU ceiling, persistent-violation fallback) that override any learned or forecast decision.

Target: AWS `ap-southeast-2`, 1-6 `t3.micro` instances behind an Application Load Balancer.

## Headline results

Simulated on a held-out 240-minute spike trace (details in [`docs/FINAL_REPORT.md`](docs/FINAL_REPORT.md)):

| Policy | Violations (min) | Cost | Scaling actions |
|---|:---:|:---:|:---:|
| Reactive threshold | 4 | $0.151 | 37 |
| AWS target tracking (modelled) | 4 | $0.182 | 35 |
| Forecast-driven threshold | 3 | $0.201 | 35 |
| Tabular Q-learning | 0 | ~$0.295 | 4 |
| DQN | 0-30 (unstable across seeds) | $0.06-0.33 | 1-30 |

Forecasting a spike from history is inherently limited (3-minute MAPE 14-22% on the held-out trace), and under-prediction is the dangerous direction: a -30% forecast bias causes 30 violation minutes, and guardrails cut that to 5.

Two live runs on real AWS (reactive and forecast-driven, both with guardrails) scaled a real ASG 1 -> 6 -> 1. These are single runs under different load shapes, so they show the system works end to end, not that one policy beats the other. Q-learning and DQN were evaluated in simulation only.

## Repository layout

```
app/server.py            CPU-bound HTTP service run on the instances (/health, /work?units=N)
src/forecast.py          forecasters + accuracy metrics (MAE, RMSE, MAPE)
src/experiment.py        simulator, baselines, Q-learning, misprediction study
src/dqn.py               NumPy DQN
src/controller.py        live decision rules (reactive, forecast-driven) + guardrails
src/config.py            settings from .env / environment
scripts/demo.py          narrated terminal walkthrough for the screencast
scripts/live_demo.py     live AWS demo: up | run | status | down
scripts/deploy-phase1.ps1, calibrate.py, run_constant_load.py, make_figures.py
docs/FINAL_REPORT.md     full technical report
docs/DEMO_SCRIPT.md      timed screencast outline
results/                 metrics, figures, calibration data, live-run traces
PROJECT_LOG.md          phase-by-phase log
```

## Setup

```bash
pip install -r requirements.txt          # numpy, matplotlib
cp .env.example .env                     # then fill in; .env is git-ignored
```

`.env` holds configuration only (AWS profile, region, VPC / subnet / AMI IDs). **AWS keys never go in `.env` or the repo**: configure an AWS CLI profile (`aws configure --profile ia-autoscaler`) and set `AWS_PROFILE`.

## Run it (no AWS needed)

Run from the project root.

```bash
python src/forecast.py          # forecaster accuracy        -> results/forecast_metrics.json
python src/experiment.py        # policies + misprediction   -> results/metrics.json, misprediction_metrics.json
python src/dqn.py               # DQN, 3 seeds               -> results/dqn_metrics.json
python scripts/make_figures.py  # all figures                -> results/*.png
python scripts/demo.py --pause  # narrated walkthrough of the results
```

## Live AWS demo (costs money)

Needs the ASG, launch template, target group and security group from `scripts/deploy-phase1.ps1`, plus a configured AWS profile. A run costs about US$0.15 (ALB plus up to 6 `t3.micro`).

```bash
python scripts/live_demo.py up                              # create ALB, ASG to 1 instance (~4 min)
python scripts/live_demo.py run                             # reactive + guardrails, step burst (~11 min)
python scripts/live_demo.py run --policy forecast --ramp    # forecast-driven + guardrails, gradual ramp (~20 min)
python scripts/live_demo.py down                            # ASG to 0, delete ALB. Always run this afterwards.
```

Traces are saved to `results/live_demo_log_<policy>.json`. Resources are tagged `project=ia-autoscaler`; a US$5 budget alert was set on the account.

## Caveats

- Policy comparisons are simulated on synthetic traces; only calibration (15 step-load runs), one target-tracking load test and the two live runs used real AWS.
- The target-tracking baseline is a model of the policy, not a measurement of AWS.
- Energy is a linear power proxy (3 W idle, 11 W peak), not measured.
- The single-process server saturates near 50% CPU, so a CPU-only scaling rule never fires under overload; the latency guardrail does the scaling.

See the report's Section 9 for the full list of limitations.
