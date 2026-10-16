# Phase 0: Infrastructure Plan and Safety Check

## Scope

This project will build an RL-controlled EC2 Auto Scaling Group in `ap-southeast-2` only. It starts with a simple CPU-bound HTTP application, measures its real behaviour, calibrates a local simulator, trains and evaluates RL policies locally, then runs short real-AWS comparison experiments.

## Proposed infrastructure

| Resource | Name pattern | Quantity / limit | Purpose |
| --- | --- | --- | --- |
| Security group | `ia-autoscaler-web-sg` | 1 | Allows HTTP to the load balancer and ALB-to-instance HTTP only. |
| Launch template | `ia-autoscaler-lt` | 1 | Defines a `t3.micro` app instance and startup script. |
| Application Load Balancer | `ia-autoscaler-alb` | 1 | Sends HTTP traffic to healthy application instances. |
| Target group | `ia-autoscaler-tg` | 1 | HTTP health check endpoint: `/health`. |
| Auto Scaling Group | `ia-autoscaler-asg` | Min 1, max 6 | Runs application instances and is controlled by the benchmark/controller. |
| CloudWatch metrics | AWS-managed | 1-minute reads | Reads CPU, ALB request count, target response time, and healthy-target count. |
| Local controller | local machine | 1 process | Runs once per minute, selects RL/reactive action, then sets ASG desired capacity. |
| Local load generator | local machine | 1 process | Generates controlled traffic; no second EC2 load-generator instance. |

All resources will be tagged `project=ia-autoscaler` and named with the same prefix. No NAT gateway, database, Elastic IP, or separate load-generator instance is planned.

## Cost estimate

Actual pricing varies by usage and AWS updates. The cost drivers are EC2 instance-hours, the ALB hourly charge, and ALB LCU usage. AWS charges an Application Load Balancer for each running hour and for LCU consumption; partial ALB hours are billed as full hours. The planned light load should use low LCU capacity, but it is still metered.

| Run state | Approximate hourly cost (USD) | Assumption |
| --- | ---: | --- |
| Minimum test state | about $0.04–$0.05/hr | 1 `t3.micro`, one ALB, light LCU usage. |
| Six-instance safety maximum | about $0.11–$0.14/hr | 6 `t3.micro` instances, one ALB, light LCU usage. |

The `$5` budget should be treated as an alert, not as a spending cap. Compute and the ALB will be deleted after each real-AWS session. A 1-hour six-instance experiment should remain well below the budget, but unattended resources could exceed it over time.

## Evaluation design

- Simulator inputs: measured per-instance capacity, boot delay, and the p95 latency-versus-utilisation curve.
- Workloads: synthetic daily, noisy, spike, ramp, sustained high/low traces plus a scaled public trace; held-out spike and out-of-distribution traces remain test-only.
- Baselines: fixed peak-sized provisioning, reactive CPU threshold scaling, and AWS target tracking (real-AWS comparison).
- RL: tabular Q-learning first, then a deep RL policy; train over multiple seeds.
- State: request rate, recent rate change, active and booting instances, CPU utilisation, time-of-day, and optional short forecast.
- Action: scale in one, hold, scale out one.
- Deployment guardrails: bounds 1–6, emergency scale-out at a hard CPU ceiling, rate-limited scale-in, and reactive fallback after persistent violations.

## Teardown procedure

1. Stop the local controller and load generator.
2. Set the ASG desired/minimum capacity to zero only when teardown is explicitly approved.
3. Delete the ASG, wait for instances to terminate, then delete the launch template.
4. Delete the ALB, listener, target group, and project security group.
5. Query all resources tagged `project=ia-autoscaler` in `ap-southeast-2`; report any remaining resources and hourly-cost exposure.

## Approval requested

Approve this plan before any resource is created. The first create step will provision only the listed resources, starting at one `t3.micro` instance and never exceeding six.
