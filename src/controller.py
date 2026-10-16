"""Minute-based reactive/RL deployment controller with safety guardrails."""
import argparse, json, subprocess, time
import config
from datetime import datetime, timedelta, timezone

def aws(args, profile, region):
    command=['aws',*args,'--profile',profile,'--region',region,'--output','json','--no-cli-pager']
    return json.loads(subprocess.check_output(command,text=True))

def metric(namespace, name, dimensions, profile, region):
    end=datetime.now(timezone.utc); start=end-timedelta(minutes=5)
    args=['cloudwatch','get-metric-statistics','--namespace',namespace,'--metric-name',name,'--dimensions',*dimensions,'--start-time',start.isoformat(),'--end-time',end.isoformat(),'--period','60','--statistics','Average']
    points=aws(args,profile,region).get('Datapoints',[])
    return max((p['Average'] for p in points),default=0.0)

def decide(cpu, desired, consecutive_violations, policy='reactive'):
    # Guardrails override any learned policy.
    if cpu >= 80: return 1,'hard_cpu_scale_out'
    if consecutive_violations >= 2: return 1,'persistent_violation_fallback'
    if policy == 'rl':
        # Learned policies (Q-learning, DQN) are trained and evaluated in the simulator only (src/experiment.py, src/dqn.py).
        raise NotImplementedError("--policy rl is simulation-only; the forecast-driven policy runs live via scripts/live_demo.py --policy forecast")
    if policy == 'reactive':
        if cpu > 70: return 1,'reactive_scale_out'
        if cpu < 30 and desired > 1: return -1,'reactive_scale_in'
    return 0,'hold'

def decide_predictive(cpu, consecutive_violations, rate, forecast, active, booting, capacity_rps=8.0):
    """Forecast-driven policy: the same guardrails, then the shared forecast threshold rule (src/forecast.py)."""
    from forecast import predictive_action
    if cpu >= 80: return 1,'hard_cpu_scale_out'
    if consecutive_violations >= 2: return 1,'persistent_violation_fallback'
    a=predictive_action(rate,forecast,active,booting,capacity_rps)
    return a,{1:'forecast_scale_out',-1:'forecast_scale_in',0:'hold'}[a]

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--profile',default=config.AWS_PROFILE); p.add_argument('--region',default=config.AWS_REGION); p.add_argument('--asg',default=config.ASG_NAME); p.add_argument('--policy',choices=['reactive','rl'],default='reactive'); p.add_argument('--once',action='store_true'); args=p.parse_args()
    violations=0
    while True:
        group=aws(['autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names',args.asg],args.profile,args.region)['AutoScalingGroups'][0]
        cpu=metric('AWS/EC2','CPUUtilization',['Name=AutoScalingGroupName,Value='+args.asg],args.profile,args.region)
        action,reason=decide(cpu,group['DesiredCapacity'],violations,args.policy)
        next_capacity=max(1,min(6,group['DesiredCapacity']+action))
        if next_capacity != group['DesiredCapacity']:
            subprocess.check_call(['aws','autoscaling','set-desired-capacity','--auto-scaling-group-name',args.asg,'--desired-capacity',str(next_capacity),'--profile',args.profile,'--region',args.region,'--no-cli-pager'])
        print(json.dumps({'time':datetime.now(timezone.utc).isoformat(),'cpu':cpu,'current':group['DesiredCapacity'],'next':next_capacity,'reason':reason}))
        if args.once: break
        time.sleep(60)
