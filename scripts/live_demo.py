"""Live AWS demo: bring the stack up, drive load, watch the guarded controller scale, tear down.

  python scripts/live_demo.py up        # create ALB + listener, ASG min/desired = 1, wait until healthy (~4 min)
  python scripts/live_demo.py status    # ASG capacity, instances, ALB endpoint
  python scripts/live_demo.py run [--policy forecast] [--ramp]   # load profile + reactive or forecast-driven controller, both with guardrails
  python scripts/live_demo.py down      # ASG to 0, delete ALB + listener (stops billing)

Needs the existing ASG/launch template/target group/security group from deploy-phase1.ps1 and AWS profile `ia-autoscaler`.
Cost while up: ALB ~US$0.03/h plus ~US$0.01/h per t3.micro. Always run `down` afterwards.
"""
import argparse, json, subprocess, sys, threading, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
from controller import decide, decide_predictive
from experiment import training_set, make_forecasters, CAPACITY_RPS
from calibrate import stage

import config   # reads .env / environment (see .env.example)
PROFILE, REGION, ASG, ALB, TG, SG_NAME, SUBNETS = config.AWS_PROFILE, config.AWS_REGION, config.ASG_NAME, config.ALB_NAME, config.TG_NAME, config.SG_NAME, config.SUBNET_IDS

def aws(*a, text=False):
    cmd = ['aws', *a, '--profile', PROFILE, '--region', REGION, '--no-cli-pager']
    if a[1] == 'wait': subprocess.check_call(cmd); return None   # `wait` subcommands take no --output
    for attempt in range(5):   # transient network errors happen on long runs
        try: out = subprocess.check_output(cmd + (['--output', 'text'] if text else ['--output', 'json']), text=True, stderr=subprocess.DEVNULL).strip(); break
        except subprocess.CalledProcessError:
            if attempt == 4: raise
            time.sleep(5)
    return out if text else (json.loads(out) if out else None)

def find_alb():
    out = aws('elbv2', 'describe-load-balancers', '--query', f"LoadBalancers[?LoadBalancerName=='{ALB}'].[LoadBalancerArn,DNSName]", text=True)
    return out.split() if out else None

def tg_arn(): return aws('elbv2', 'describe-target-groups', '--names', TG, '--query', 'TargetGroups[0].TargetGroupArn', text=True)

def asg():
    return aws('autoscaling', 'describe-auto-scaling-groups', '--auto-scaling-group-names', ASG)['AutoScalingGroups'][0]

def wait_healthy(timeout=600):
    """Poll until every target in the target group is healthy (the CLI waiters are version-dependent)."""
    end = time.time() + timeout
    while time.time() < end:
        states = aws('elbv2', 'describe-target-health', '--target-group-arn', tg_arn(), '--query', 'TargetHealthDescriptions[].TargetHealth.State', text=True).split()
        if states and all(x == 'healthy' for x in states): return
        time.sleep(15)
    sys.exit('timed out waiting for healthy targets')

def up():
    if not find_alb():
        if not SUBNETS: sys.exit('set SUBNET_IDS in .env (see .env.example)')
        sg = aws('ec2', 'describe-security-groups', '--filters', f'Name=group-name,Values={SG_NAME}', '--query', 'SecurityGroups[0].GroupId', text=True)
        print('creating load balancer...')
        arn = aws('elbv2', 'create-load-balancer', '--name', ALB, '--subnets', *SUBNETS, '--security-groups', sg, '--scheme', 'internet-facing', '--type', 'application',
                  '--tags', 'Key=project,Value=ia-autoscaler', '--query', 'LoadBalancers[0].LoadBalancerArn', text=True)
        aws('elbv2', 'wait', 'load-balancer-available', '--load-balancer-arns', arn)
        aws('elbv2', 'create-listener', '--load-balancer-arn', arn, '--protocol', 'HTTP', '--port', '80', '--default-actions', f'Type=forward,TargetGroupArn={tg_arn()}')
    print('scaling ASG to 1 instance...')
    aws('autoscaling', 'update-auto-scaling-group', '--auto-scaling-group-name', ASG, '--min-size', '1', '--max-size', '6', '--desired-capacity', '1')
    print('waiting for a healthy target (about 3-4 minutes)...')
    wait_healthy()
    status()

def status():
    g = asg(); alb = find_alb()
    print(f"ASG {ASG}: min={g['MinSize']} desired={g['DesiredCapacity']} max={g['MaxSize']} instances={len(g['Instances'])} "
          f"({', '.join(i['LifecycleState'] for i in g['Instances']) or 'none'})")
    print('ALB endpoint:', f'http://{alb[1]}' if alb else 'not created')

def cpu_pct(minutes=3):
    end = datetime.now(timezone.utc)
    pts = aws('cloudwatch', 'get-metric-statistics', '--namespace', 'AWS/EC2', '--metric-name', 'CPUUtilization', '--dimensions', f'Name=AutoScalingGroupName,Value={ASG}',
              '--start-time', (end - timedelta(minutes=minutes)).isoformat(), '--end-time', end.isoformat(), '--period', '60', '--statistics', 'Average').get('Datapoints', [])
    pts.sort(key=lambda p: p['Timestamp']); return pts[-1]['Average'] if pts else 0.0

def alb_p95_ms(alb_arn, minutes=3):
    """Latest 1-minute p95 of ALB TargetResponseTime in ms (0 if no traffic)."""
    end = datetime.now(timezone.utc)
    pts = aws('cloudwatch', 'get-metric-statistics', '--namespace', 'AWS/ApplicationELB', '--metric-name', 'TargetResponseTime',
              '--dimensions', 'Name=LoadBalancer,Value=' + alb_arn.split('loadbalancer/')[1], '--start-time', (end - timedelta(minutes=minutes)).isoformat(),
              '--end-time', end.isoformat(), '--period', '60', '--extended-statistics', 'p95').get('Datapoints', [])
    pts.sort(key=lambda p: p['Timestamp']); return pts[-1]['ExtendedStatistics']['p95'] * 1000 if pts else 0.0

def request_rates(alb_arn, minutes=12):
    """Per-minute request rate (rps), oldest first, for minutes CloudWatch has already published.

    CloudWatch lags by about a minute, so the newest minute is often missing; trailing missing minutes are dropped
    (not read as zero traffic), interior missing minutes mean no requests."""
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0); start = end - timedelta(minutes=minutes)
    pts = aws('cloudwatch', 'get-metric-statistics', '--namespace', 'AWS/ApplicationELB', '--metric-name', 'RequestCount',
              '--dimensions', 'Name=LoadBalancer,Value=' + alb_arn.split('loadbalancer/')[1], '--start-time', start.isoformat(), '--end-time', end.isoformat(),
              '--period', '60', '--statistics', 'Sum').get('Datapoints', [])
    # the CLI reports timestamps in the local timezone, so normalise to UTC before matching minutes
    by = {datetime.fromisoformat(p['Timestamp']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M'): p['Sum'] / 60 for p in pts}
    series = [by.get((start + timedelta(minutes=i)).strftime('%Y-%m-%dT%H:%M')) for i in range(minutes)]
    while series and series[-1] is None: series.pop()
    return [x or 0.0 for x in series] or [0.0]

def run(args):
    alb = find_alb()
    if not alb: sys.exit('stack is down; run `up` first')
    forecaster = make_forecasters([l for sd in (1, 2, 3) for l in training_set(sd)])['ridge_ar'] if args.policy == 'forecast' else None
    endpoint = f'http://{alb[1]}'
    if args.ramp:   # gradual build-up, so a trend exists for the forecaster to extrapolate
        steps = list(range(args.low_workers + 2, args.high_workers + 1, 2))
        phases = [('low', args.low_workers, args.low_seconds)] + [('ramp', w, args.ramp_step_seconds) for w in steps] + [('HIGH', args.high_workers, args.high_seconds), ('low', args.low_workers, args.cool_seconds)]
    else:
        phases = [('low', args.low_workers, args.low_seconds), ('HIGH', args.high_workers, args.high_seconds), ('low', args.low_workers, args.cool_seconds)]
    state = {'phase': 'starting', 'workers': 0, 'last': {}, 'done': False}
    def load():
        for name, workers, secs in phases:
            state.update(phase=name, workers=workers); r = stage(endpoint, workers, secs, args.units); state['last'] = r
            print(f"   [load] {name:4} {workers:2} workers: {r['rps']:.1f} rps, p95 {r['p95_ms'] or 0:.0f} ms, failures {r['failures']}", flush=True)
        state['done'] = True
    threading.Thread(target=load, daemon=True).start()
    violations = 0; log = []
    print(f"{'time':>8} {'load':>10} {'cpu%':>6} {'alb p95':>8} {'rps':>5} {'fcst':>5} {'inst':>9}  controller decision")
    t0 = time.time()
    while not state['done']:
        time.sleep(args.interval)
        g = asg(); cpu = cpu_pct(); p95 = alb_p95_ms(alb[0]); violations = violations + 1 if p95 > 500 else 0; desired = g['DesiredCapacity']; inservice = sum(i['LifecycleState'] == 'InService' for i in g['Instances'])
        booting = max(0, desired - inservice); fc = rate = 0.0
        if forecaster:
            hist = request_rates(alb[0]); rate = hist[-1]; fc = forecaster(hist, 3)
            action, reason = decide_predictive(cpu, violations, rate, fc, inservice, booting, CAPACITY_RPS)
        else:
            action, reason = decide(cpu, desired, violations, 'reactive')
        nxt = max(1, min(6, desired + action))
        if nxt != desired: aws('autoscaling', 'set-desired-capacity', '--auto-scaling-group-name', ASG, '--desired-capacity', str(nxt))
        log.append(dict(t=round(time.time() - t0), phase=state['phase'], workers=state['workers'], cpu=round(cpu, 1), alb_p95_ms=round(p95), rps=round(rate, 1), forecast_rps=round(fc, 1), desired=desired, in_service=inservice, next=nxt, reason=reason))
        print(f"{int(time.time()-t0):>7}s {state['phase']+'/'+str(state['workers']):>10} {cpu:>6.1f} {p95:>6.0f}ms {rate:>5.1f} {fc:>5.1f} {f'{inservice}/{desired}->{nxt}':>9}  {reason}", flush=True)
    open(f'results/live_demo_log_{args.policy}.json', 'w').write(json.dumps(log, indent=2))
    print('saved results/live_demo_log_<policy>.json; run `down` to stop billing')

def down():
    print('scaling ASG to 0...')
    aws('autoscaling', 'update-auto-scaling-group', '--auto-scaling-group-name', ASG, '--min-size', '0', '--desired-capacity', '0')
    alb = find_alb()
    if alb:
        for l in aws('elbv2', 'describe-listeners', '--load-balancer-arn', alb[0])['Listeners']: aws('elbv2', 'delete-listener', '--listener-arn', l['ListenerArn'])
        aws('elbv2', 'delete-load-balancer', '--load-balancer-arn', alb[0])
    print('ALB deleted.'); status()

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('cmd', choices=['up', 'status', 'run', 'down'])
    p.add_argument('--policy', choices=['reactive', 'forecast'], default='reactive'); p.add_argument('--ramp', action='store_true'); p.add_argument('--ramp-step-seconds', type=int, default=60)
    p.add_argument('--interval', type=int, default=30); p.add_argument('--units', type=int, default=500000)
    p.add_argument('--low-workers', type=int, default=2); p.add_argument('--high-workers', type=int, default=24)
    p.add_argument('--low-seconds', type=int, default=90); p.add_argument('--high-seconds', type=int, default=360); p.add_argument('--cool-seconds', type=int, default=300)
    a = p.parse_args()
    {'up': up, 'status': status, 'down': down}.get(a.cmd, lambda: run(a))()
