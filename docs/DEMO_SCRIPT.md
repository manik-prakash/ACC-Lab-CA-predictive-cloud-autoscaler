# Screencast script (about 8-10 minutes)

**Before recording:** open a terminal in the project root, `pip install -r requirements.txt`, and have these ready in tabs: `docs/FINAL_REPORT.md`, the four figures in `results/`, and (optional) the AWS console on EC2 > Auto Scaling groups.
Run the demo with `python scripts/demo.py --pause` and press Enter between sections. Add `--rerun` once, off camera, if you want fresh numbers.

| Time | Show | Say |
|---|---|---|
| 0:00 | Title / `PROJECT_LOG.md` | Project: ML-based resource manager that predicts workload and scales an AWS Auto Scaling Group (1-6 t3.micro behind an ALB). |
| 0:45 | demo section 1 | Challenge: instances take 3 minutes to boot, so reacting to current load is too late. |
| 1:30 | demo section 2, `calibration_latency.png`, AWS console (ASG exists, desired = 0) | Real AWS measurement: 15 step-load runs, about 8 RPS per instance, 6,108 live requests with zero failures. The stack is scaled to zero to stop charges; budget $5. Client p95 is ~1 s because the load generator was in India and AWS in Sydney; ALB-side p95 was < 445 ms. |
| 2:30 | demo section 3 | Inputs: request rate, rate change, active and booting instances, plus a 3-minute forecast. Forecaster: ridge-regression autoregression. Controller: Q-learning, plus a DQN comparison. Horizon = 3 min = boot lag. |
| 3:30 | demo section 4, `forecast_vs_actual.png` | Prediction accuracy (MAE/MAPE). The learned model only wins on noisy or ramping load; nobody predicts a spike onset from history. |
| 4:30 | demo section 5, `simulated_policy_comparison.png` | Utilization, latency, cost, energy, now including a model of AWS target tracking (35 actions, like reactive). Reactive: cheapest but 37 scaling actions. Q-learning: 0 violations, 4 actions, but about 2x the cost. DQN: collapses on 2 of 3 seeds. Simulated on a held-out trace; energy is a 3 W to 11 W linear proxy. |
| 6:00 | demo section 6, `misprediction_robustness.png` | What if the prediction is wrong? Under-predicting by 30% gives 30 violation minutes; guardrails (80% ceiling, 2-violation fallback) cut it to 5. Over-prediction wastes money; noise causes thrashing. |
| 7:30 | `src/controller.py` guardrail function, `FINAL_REPORT.md` section 9 | Live controller = reactive or forecast-driven policy, both with guardrails. Q-learning and DQN are simulation-only. Limitations: synthetic traces, only calibration ran on real AWS. |
| 8:30 | Wrap-up | Trade-offs: no policy wins on cost, stability and SLO at once; guardrails are essential. |

**If asked "why is Q-learning so expensive?"** The reward penalises one SLO violation at 8.0 against 0.00025 per instance-minute, so it over-provisions.
**If asked "why not test on AWS?"** Budget and boot lag; calibration was on AWS and the simulator is built from it.

## Optional live AWS segment (about 12-20 minutes, about US$0.15 per run)
1. Start about 5 minutes before you record: `python scripts/live_demo.py up` (creates the ALB, brings the ASG to 1 instance, waits until healthy). Check with `python scripts/live_demo.py status`.
2. On camera, show the EC2 > Auto Scaling groups page, then run `python scripts/live_demo.py run` (about 11 minutes; speed up the video or use `--high-seconds 240 --cool-seconds 180` for a shorter take; the forecast run below takes about 20). It runs low load, then a heavy burst (24 workers), then low load, with the reactive-plus-guardrail controller printing a decision every 30 s.
3. For the predictive version use `python scripts/live_demo.py run --policy forecast --ramp` (gradual load build-up, so the forecaster has a trend to extrapolate; the log shows `rps`, `fcst` and `forecast_scale_out` decisions). Expected for the forecast run: `forecast_scale_out` fires while the ALB p95 is still under 500 ms (peak about 430 ms), reaching 6 instances, then `forecast_scale_in` steps back to 1. Expected for the default run: ALB p95 jumps past 500 ms, `persistent_violation_fallback` scales the group 1 -> 6 one instance per step, then `reactive_scale_in` brings it back to 1. The trace is saved to `results/live_demo_log.json`.
4. Afterwards, always run `python scripts/live_demo.py down` (ASG to 0, ALB deleted).

Talking point: CPU only reaches about 50% even when the server is overloaded, because the single-process Python server uses one of the two vCPUs. A CPU-only rule would never scale out, so the p95-latency guardrail does the work. This also explains the ~42% CPU measured at 8-9.6 RPS in calibration.
