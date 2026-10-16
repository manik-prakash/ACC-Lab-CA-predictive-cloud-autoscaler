# RL Autoscaler Project Log

## Phase 0 — Plan and safety check (2026-10-12)

### Confirmed
- AWS account: `<AWS_ACCOUNT_ID>`
- Region: `ap-southeast-2` (Asia Pacific — Sydney); this is the only region permitted for the project.
- Scoped CLI identity: `ia-autoscaler-cli`.
- Budget: `ia-autoscaler-budget`, a healthy USD 5 monthly cost budget. Notifications are configured for actual spend at 85% and 100%, plus forecasted spend at 100%.
- Existing project-tagged VPCs: none.
- Existing Auto Scaling Groups in the permitted region: none.
- Existing load balancers in the permitted region: none.

### Safety decisions
- Every created project resource receives the tag `project=ia-autoscaler`.
- EC2 type: `t3.micro` (pending student confirmation; `t2.micro` only if explicitly requested).
- Auto Scaling Group bounds: minimum 1, maximum 6.
- No NAT gateway, database, or other unlisted service will be created.
- No creation, modification, or deletion occurs before the student approves the Phase 0 plan.

### Completed
- Completed simulator-to-AWS fidelity validation and comparative policy benchmarks.
- Confirmed full infrastructure teardown: 0 running EC2 instances, ALB and target groups deleted, 0 ongoing costs.

## Phase 1 — Infrastructure
- Created tagged security group, launch template, ALB, target group, listener and ASG in `ap-southeast-2`.
- Verified `GET /health` through the ALB.
- Verified manual scale-out to two healthy instances, then returned desired capacity to one.

## Phase 2 — Calibration
- Ran 15 one-minute client-side workload observations (five concurrency levels, three repeats); all requests succeeded.
- Client p95 increased from about 0.75 seconds at 1.4 rps to about 1.0–1.1 seconds at 9.6 rps.
- Observed EC2 CPU peaked near 42% average during the completed load run.
- Observed ALB target-response p95 stayed below roughly 445 ms. Client and ALB measurements are recorded separately because they measure different paths (transcontinental client network transit ~300ms vs Sydney local target processing).
- Scale-out target health was confirmed; estimated boot delay settled at ~3 minutes.

## Phase 3 — Simulator Calibration & Target Tracking Fidelity
- Parameterized local simulator with calibrated single-instance capacity (~8 RPS) and 3-minute boot lag.
- Modeled polynomial latency degradation past 70% CPU threshold.
- Verified against real-AWS target tracking load test (`target_tracking_load.json`): 6,108 requests at 10.18 RPS with 100% success rate (0 failures).

## Phase 4 — Baseline Policy Benchmarks
- **Reactive Rule-Based Policy**: Evaluated under 240-minute synthetic spike workload.
  - Average instances: 2.52, Average CPU: 47.6%.
  - p95 latency: 70.0 ms with 4 violation minutes.
  - Cost: $0.151, Energy: 27.02 Wh.
  - Drawback: High oscillation count (37 scaling actions), inducing mechanical wear and thrashing.

## Phase 5 — Tabular Reinforcement Learning (re-run in Phase 8 with a held-out test)
- Trained on a diverse trace set per seed, evaluated on the held-out `spike` trace (seed 99, spike at minutes 110-140). Earlier numbers (2 actions, 0 violations, $0.178) came from training and testing on the same trace and are superseded.
- Seeds 1-3: 4.89-4.92 avg instances, p95 224 ms, 0 violations, 4 scaling actions, $0.293-0.295, 20.7 Wh.

## Phase 6 — Deep RL (DQN) Prototype & Degeneracy Analysis (re-run in Phase 8)
- Seed 1: 1.41 instances, 30 violations, $0.084. Seed 2: locked at 1.0 instance, 94.9% utilization, p95 3,189 ms, 30 violations, 30 scaling actions. Seed 3: 5.47 instances, 0 violations, $0.328.
- Unstable across seeds: small MLP, naive replay, no target network.

## Phase 7 — Teardown & Cost Safety Verification
- Auto Scaling Group desired and minimum capacity set to 0; all EC2 instances terminated.
- Application Load Balancer (`ia-autoscaler-alb`), listeners, and target groups deleted.
- Launch template and project security groups decommissioned.
- Total spend audited and verified strictly below the $5.00 safety budget limit.
- Verified zero active compute resources remaining in `ap-southeast-2`.


## Phase 8 — Forecasting, misprediction study and report fixes
- Added `src/forecast.py`: naive, moving average, Holt, window-trend and a learned ridge-AR forecaster. Horizon 3 min (= boot lag). MAE/RMSE/MAPE at h = 1, 3, 5 on seen and held-out traces -> `results/forecast_metrics.json`.
- `src/experiment.py`: optional forecast feature in the state, `predictive_reactive` and forecast-aware Q-learning, injected forecast error, optional guardrails in the simulator. Training uses separate traces from the held-out test.
- Misprediction study (bias +/-30%, noise, missed spike; with and without guardrails) -> `results/misprediction_metrics.json`.
- Q-learning seeds 1 and 2 were identical because every seed trained on the same fixed trace. Seeds now train on independent traces.
- `src/controller.py --policy rl` now raises NotImplementedError instead of silently holding.
- `docs/FINAL_REPORT.md` rewritten from the new results: features/algorithm/horizon (4.4), prediction accuracy (5.1), "When the Prediction Is Wrong" (6), limitations (9). AWS account ID removed from this log.
- Added `scripts/demo.py` (narrated, `--pause` for recording) and `docs/DEMO_SCRIPT.md` (screencast outline). AWS verified idle: ASG `ia-autoscaler-asg` at 0/0 instances, no ALB, no running instances.
- Live AWS demo (2026-10-15): `scripts/live_demo.py up/run/status/down`. Controller scaled 1->6->1 under a 24-worker burst via the p95 guardrail; CPU stayed <= ~50% (single-process server). Trace in `results/live_demo_log_reactive.json`. Stack torn down afterwards (ASG 0, ALB deleted).
- Added a modelled AWS target-tracking baseline (60% target, 15-min scale-in) to the simulator and report. Added a forecast-driven live policy (`controller.decide_predictive`, `live_demo.py run --policy forecast --ramp`). 
- Live forecast-driven run (2026-10-16, 3rd attempt; first two exposed a CloudWatch-lag bug and a timezone bug, fixed): ramp load, peak ALB p95 424 ms, 0 of 33 ticks over 500 ms, 1->6->1 instances. `results/live_demo_log_forecast.json`. Stack torn down again (ASG 0, ALB deleted).
- Config/credentials: `src/config.py` reads `.env` (git-ignored; template `.env.example`). VPC/subnet/AMI IDs and the AWS CLI path were removed from `deploy-phase1.ps1`; AWS keys stay in the AWS CLI profile. Added git repo with remote `origin`.
