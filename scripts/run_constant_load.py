import argparse, json, sys
sys.path.insert(0, 'scripts')
from calibrate import stage

p=argparse.ArgumentParser(); p.add_argument('--endpoint',required=True); p.add_argument('--workers',type=int,default=8); p.add_argument('--seconds',type=int,default=600); p.add_argument('--units',type=int,default=500000); args=p.parse_args()
print(json.dumps(stage(args.endpoint,args.workers,args.seconds,args.units)),flush=True)
