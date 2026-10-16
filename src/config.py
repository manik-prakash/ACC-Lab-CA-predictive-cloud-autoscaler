"""Project settings from environment variables, with an optional `.env` file in the project root.

Real environment variables win over `.env`. Secrets (AWS keys) do NOT belong here: they stay in the AWS CLI
profile named by AWS_PROFILE (`aws configure --profile ...`, stored in ~/.aws/credentials).
"""
import os
from pathlib import Path

def _load_dotenv():
    f = Path(__file__).resolve().parent.parent / '.env'
    if not f.exists(): return
    for line in f.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"\''))

_load_dotenv()
def get(name, default=None): return os.environ.get(name, default)

AWS_PROFILE = get('AWS_PROFILE', 'ia-autoscaler')
AWS_REGION = get('AWS_REGION', 'ap-southeast-2')
ASG_NAME = get('ASG_NAME', 'ia-autoscaler-asg')
ALB_NAME = get('ALB_NAME', 'ia-autoscaler-alb')
TG_NAME = get('TG_NAME', 'ia-autoscaler-tg')
SG_NAME = get('SG_NAME', 'ia-autoscaler-web-sg')
SUBNET_IDS = [x for x in get('SUBNET_IDS', '').replace(' ', '').split(',') if x]
