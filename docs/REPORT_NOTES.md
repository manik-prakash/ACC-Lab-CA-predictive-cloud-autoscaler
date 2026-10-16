# Report-ready factual notes

## Problem
An RL controller chooses scale-in, hold, or scale-out actions once per minute for a 1–6 instance EC2 Auto Scaling Group. The objective balances latency SLO compliance, instance cost, energy estimate, and scaling stability.

## Implemented system
- Region: `ap-southeast-2`.
- Runtime: Amazon Linux 2023 `t3.micro` instances behind an Application Load Balancer.
- App endpoints: `/health` and CPU-bound `/work?units=...`.
- Controller state: recent demand/CPU, active capacity, booting capacity, and optional time features.
- Controller action: -1, 0, +1 instance, bounded to [1, 6].
- Guardrails: forced scale-out at 80% CPU, reactive fallback after persistent violation, bounded scale-in.

## Calibration evidence (2026-10-12)
- Client load test: 15 one-minute observations (five concurrency levels x three repeats), all requests successful.
- At 1.4 rps, client p95 was roughly 0.75 seconds.
- At 9.6 rps, client p95 was roughly 1.0–1.1 seconds.
- ALB `TargetResponseTime` p95 during the observed workload remained below roughly 0.445 seconds.
- EC2 CPU reached roughly 42% average during the observed workload.
- Limitation: client-side and ALB-side latency differ; the report should explain the client/network component rather than treating them as interchangeable.

## Energy model
Use idle power 3 W and peak power 11 W per `t3.micro` proxy model. At minute `t`: `P = 3 + (11 - 3) * CPU_utilisation`. Sum `P / 60` across instance-minutes to report Wh. This is an assumption, not a direct EC2 power measurement.

## Results (simulated, held-out spike trace; see FINAL_REPORT.md for full tables)
- Calibrated capacity ~8.0 RPS per instance, boot delay ~3 min. Real-AWS target tracking: 6,108 requests at 10.18 RPS, 0 errors.
- Forecast MAPE at h=3 (spike trace): naive 14.5%, ridge-AR 17.8%, Holt 21.8%.
- Reactive: $0.151, 27.02 Wh, 4 violations, 37 actions. Forecast-driven threshold: $0.201, 23.29 Wh, 3 violations, 35 actions.
- Tabular Q-learning (held-out): ~$0.295, 20.7 Wh, 0 violations, 4 actions. DQN: seed-dependent collapse.
- Wrong forecasts: -30% bias gives 30 violation minutes unguarded and 5 with guardrails; missed spike 30 -> 3.
- Live AWS controller runs (Oct 15-16): reactive + guardrails on a step burst (peak ALB p95 1,854 ms, 1->6->1 instances); forecast-driven + guardrails on a ramp (peak p95 424 ms, 0 of 33 ticks over 500 ms). Different load shapes, single runs. CPU saturates near 50% (single-process server), so the latency guardrail does the scaling.
- Modelled AWS target tracking (60% target, 15-min scale-in): $0.182, 35 actions, 4 violations.
- Teardown verified: ASG at 0, ALB deleted, spend under $5.
