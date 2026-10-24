# Demo script: 5-6 minutes, with a live AWS run

The live run takes longer than the video, so it is started early in Terminal B and shown at the end. Recorded traces (`demo.py` section 8) are the fallback.

## Before you press record (5 minutes)
1. `python scripts/live_demo.py status`: should show `min=1 desired=1 instances=1 (InService)` and an ALB endpoint. If not, `python scripts/live_demo.py up`.
2. **Terminal A** (project root): for the walkthrough. Type but don't run: `python scripts/demo.py --pause`
3. **Terminal B** (project root): for the live run. Type but don't run:
   `python scripts/live_demo.py run --low-seconds 30 --high-seconds 180 --cool-seconds 120`
4. **Browser tab 1:** AWS console > EC2 > Auto Scaling groups > `ia-autoscaler-asg` > Instance management (refresh shows instance count).
5. **Browser tab 2:** https://excalidraw.com with `docs/architecture.excalidraw` loaded.
6. **Image viewer / VS Code tabs:** `results/forecast_vs_actual.png`, `results/simulated_policy_comparison.png`, `results/misprediction_robustness.png`, and `docs/FINAL_REPORT.md` (sections 5, 6, 9).
7. Increase terminal font size. Close notifications.

## Script

| Time | On screen | Say |
|---|---|---|
| **0:00-0:40** | Excalidraw architecture | "This is an ML-based cloud resource manager for AWS. The Auto Scaling Group is only the actuator, since it adds and removes instances. My project replaces its decision policy: a forecaster predicts load 3 minutes ahead, which is the instance boot time, and controllers decide how many instances to run, with guardrails on top. On the left is the live AWS stack and decision layer. On the right is the simulator pipeline calibrated from real AWS measurements." |
| **0:40-1:00** | **Terminal B: press Enter** (starts the live run). Switch to AWS console tab: 1 instance. | "I've just started a live load test on the real ASG. It runs in the background, and we'll come back to it. Right now there's one instance." |
| **1:00-1:50** | Terminal A: run `demo.py --pause`; sections 1, 2, 3 (Enter between) | "Measured on real AWS: 15 step-load runs, about 8 requests per second per instance, zero failures, and a 3-minute boot lag. These numbers calibrate the simulator. Inputs are request rate, rate change, active and booting instances, plus the forecast. The forecaster is ridge-regression autoregression; the controllers are Q-learning and a DQN. Horizon is 3 minutes because an instance ordered now only helps 3 minutes later." |
| **1:50-2:40** | section 4; show `forecast_vs_actual.png` | "Prediction accuracy on a held-out spike trace: at the 3-minute horizon the error is 14 to 22 percent. A naive last-value forecast is about as good as the learned model; it only wins on noisy and ramping load. Nobody can predict the spike onset from history, which is why the next part matters." |
| **2:40-3:40** | section 5; show `simulated_policy_comparison.png` | "Utilization, latency, cost and energy for each policy, including a model of AWS target tracking. Reactive and target tracking are cheapest but thrash: 35 to 37 scaling actions. Q-learning has zero violations and only 4 actions, but costs about twice as much, because one SLO violation is penalised far more than an instance-minute. The DQN is unstable: two of three seeds collapse. Energy is a linear power estimate, not measured." |
| **3:40-4:30** | section 6; show `misprediction_robustness.png` | "What happens when the prediction is wrong? I injected forecast bias, noise and a missed spike. Under-predicting by 30 percent gives 30 violation minutes. Over-predicting just wastes money. Deterministic guardrails (scale out at 80 percent CPU or after two violations) cut that to 5, and a missed spike from 30 to 3, at some extra cost. Guardrails don't stop flapping, so production would add a cooldown." |
| **4:30-5:30** | **Terminal B output** + AWS console tab (refresh) | "Back to the live run. The load has jumped. Notice CPU stays around 50 percent even though latency is over a second, because my single-process Python server only uses one of the two vCPUs. A CPU-only rule would never scale out. The latency guardrail, `persistent_violation_fallback`, fires and the group grows from 1 toward 6 instances. Refresh the console to show new instances launching." |
| **5:30-6:00** | `FINAL_REPORT.md` section 9 (or Terminal A) | "Limitations: the policy comparison is simulated on synthetic traces, only calibration and the live runs used real AWS, and the AWS comparison is a model. Q-learning and DQN were not deployed live. The take-away is that no policy wins on cost, stability and SLO at once, and guardrails are essential." Then in Terminal B: `python scripts/live_demo.py down` ("tearing down so nothing keeps billing"). |

## Fallbacks
- **Live run shows no scaling yet at 4:30:** say "scale-out takes about 3 minutes to boot", then run `python scripts/demo.py` section 8 (it prints the recorded live traces): the reactive run peaked at 1,854 ms p95 and scaled 1 -> 6 -> 1, and the forecast-driven run stayed under 424 ms.
- **Run command errors:** `python scripts/live_demo.py status`, then retry; AWS calls retry automatically on network blips.
- **Want the predictive policy live:** `python scripts/live_demo.py run --policy forecast --ramp` takes about 20 minutes, so show its recorded trace instead.

## Likely questions
- **"Isn't this just an ASG?"** The ASG is the actuator. The project replaces its reactive policy with forecasting, RL and guardrails.
- **"Why is Q-learning so expensive?"** The reward penalises a violation (-8) against 0.00025 per instance-minute, so it over-provisions.
- **"Why simulate?"** A boot lag of 3 minutes and a $5 budget make training on real AWS impractical; calibration and the live runs tie the simulator to reality.

## After the demo
`python scripts/live_demo.py down`, then confirm with `python scripts/live_demo.py status` (`instances=0`, ALB not created). Cost of the stack while up: about $0.03/h for the ALB plus about $0.01/h per instance.
