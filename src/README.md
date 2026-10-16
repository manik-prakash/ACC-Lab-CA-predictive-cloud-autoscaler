# Local experiment runner

Run all commands from the project root (`pip install -r requirements.txt` first).

| Command | What it does | Writes |
|---|---|---|
| `python src/forecast.py` | Fits the workload forecasters, reports MAE/RMSE/MAPE at 1, 3, 5 min | `results/forecast_metrics.json` |
| `python src/experiment.py` | Reactive, forecast-driven, Q-learning and forecast-aware Q-learning on the held-out spike trace, plus the misprediction study | `results/metrics.json`, `learning_curves.csv`, `misprediction_metrics.json` |
| `python src/dqn.py` | NumPy DQN over 3 seeds | `results/dqn_metrics.json`, `dqn_curve_seed_*.csv` |
| `python scripts/make_figures.py` | Regenerates all figures (run after the three above) | `results/*.png` |

`CAPACITY_RPS` and `BOOT_MINUTES` in `experiment.py` come from the Phase 2 AWS calibration. Training traces never include the evaluation trace (`trace('spike', seed=99)`).

Settings (AWS profile, region, VPC/subnet/AMI IDs) come from a git-ignored `.env`; copy `.env.example` to `.env` and fill it in. Secrets (AWS keys) stay in the AWS CLI profile, never in `.env` or the repo.

`src/controller.py` holds the live decision rules (reactive and forecast-driven, both with guardrails). `scripts/live_demo.py up | run [--policy forecast --ramp] | status | down` drives them against real AWS (creates and deletes an ALB, costs about US$0.15 per run, always finish with `down`). `controller.py --policy rl` is simulation-only.
