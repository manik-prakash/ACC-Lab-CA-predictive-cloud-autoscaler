param(
  [string]$Profile,
  [string]$Region,
  [string]$VpcId,
  [string[]]$SubnetIds,
  [string]$ImageId
)

# Settings come from .env in the project root (see .env.example); parameters override them.
$cfg = @{}
$envFile = Join-Path $PSScriptRoot '..\.env'
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object { if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*?)\s*$') { $cfg[$Matches[1]] = $Matches[2].Trim('"', "'") } }
}
if (-not $Profile) { $Profile = if ($cfg.AWS_PROFILE) { $cfg.AWS_PROFILE } else { 'ia-autoscaler' } }
if (-not $Region) { $Region = if ($cfg.AWS_REGION) { $cfg.AWS_REGION } else { 'ap-southeast-2' } }
if (-not $VpcId) { $VpcId = $cfg.VPC_ID }
if (-not $SubnetIds -and $cfg.SUBNET_IDS) { $SubnetIds = $cfg.SUBNET_IDS -split ',' }
if (-not $ImageId) { $ImageId = $cfg.AMI_ID }
if (-not $VpcId -or -not $SubnetIds -or -not $ImageId) { throw 'Set VPC_ID, SUBNET_IDS and AMI_ID in .env (see .env.example).' }

$ErrorActionPreference = 'Stop'
$aws = if ($cfg.AWS_CLI) { $cfg.AWS_CLI } else { 'aws' }
$tagArgs = @('Key=project,Value=ia-autoscaler')

function Invoke-Aws([string[]]$Arguments) {
  & $aws @Arguments --profile $Profile --region $Region --no-cli-pager
  if ($LASTEXITCODE -ne 0) { throw "AWS command failed: $($Arguments -join ' ')" }
}

$existing = Invoke-Aws @('autoscaling','describe-auto-scaling-groups','--auto-scaling-group-names','ia-autoscaler-asg','--query','AutoScalingGroups[0].AutoScalingGroupName','--output','text')
if ($existing -eq 'ia-autoscaler-asg') { throw 'ia-autoscaler-asg already exists; refusing to overwrite it.' }

$sgId = Invoke-Aws @('ec2','describe-security-groups','--filters','Name=group-name,Values=ia-autoscaler-web-sg',("Name=vpc-id,Values={0}" -f $VpcId),'--query','SecurityGroups[0].GroupId','--output','text')
if ($sgId -eq 'None') {
  $sgId = Invoke-Aws @('ec2','create-security-group','--group-name','ia-autoscaler-web-sg','--description','HTTP access for ia-autoscaler ALB and app','--vpc-id',$VpcId,'--tag-specifications','ResourceType=security-group,Tags=[{Key=project,Value=ia-autoscaler},{Key=Name,Value=ia-autoscaler-web-sg}]','--query','GroupId','--output','text')
  Invoke-Aws @('ec2','authorize-security-group-ingress','--group-id',$sgId,'--ip-permissions','IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0,Description=Public HTTP to ALB}]') | Out-Null
  Invoke-Aws @('ec2','authorize-security-group-ingress','--group-id',$sgId,'--ip-permissions',("IpProtocol=tcp,FromPort=8080,ToPort=8080,UserIdGroupPairs=[{{GroupId={0},Description=ALB to app}}]" -f $sgId)) | Out-Null
}

$userData = @'
#!/bin/bash
set -euxo pipefail
mkdir -p /opt/ia-autoscaler
cat > /opt/ia-autoscaler/server.py <<'PY'
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import json, math, time
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        p=urlparse(self.path)
        if p.path == '/health': return self.send(200, {'status':'ok'})
        if p.path != '/work': return self.send(404, {'error':'use /health or /work?units=200000'})
        try: units=int(parse_qs(p.query).get('units',['200000'])[0])
        except ValueError: return self.send(400, {'error':'units must be an integer'})
        units=max(1000,min(units,5000000)); started=time.perf_counter(); value=0.0
        for i in range(units): value += math.sqrt((i % 997) + 1)
        self.send(200, {'units':units,'elapsed_ms':round((time.perf_counter()-started)*1000,2),'checksum':round(value,2)})
    def send(self,status,payload):
        data=json.dumps(payload).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, fmt, *args): print(fmt % args, flush=True)
ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()
PY
cat > /etc/systemd/system/ia-autoscaler.service <<'UNIT'
[Unit]
Description=IA autoscaler CPU-bound web app
After=network.target
[Service]
ExecStart=/usr/bin/python3 /opt/ia-autoscaler/server.py
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ia-autoscaler
'@
$encodedUserData = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userData))
$launchData = @{ ImageId=$ImageId; InstanceType='t3.micro'; SecurityGroupIds=@($sgId); UserData=$encodedUserData; Monitoring=@{Enabled=$true}; TagSpecifications=@(@{ResourceType='instance';Tags=@(@{Key='project';Value='ia-autoscaler'},@{Key='Name';Value='ia-autoscaler-instance'})},@{ResourceType='volume';Tags=@(@{Key='project';Value='ia-autoscaler'})}) } | ConvertTo-Json -Depth 8 -Compress
$existingLt = Invoke-Aws @('ec2','describe-launch-templates','--launch-template-names','ia-autoscaler-lt','--query','LaunchTemplates[0].LaunchTemplateId','--output','text')
if ($existingLt -eq 'None') {
  Invoke-Aws @('ec2','create-launch-template','--launch-template-name','ia-autoscaler-lt','--version-description','phase1','--launch-template-data',$launchData,'--tag-specifications','ResourceType=launch-template,Tags=[{Key=project,Value=ia-autoscaler},{Key=Name,Value=ia-autoscaler-lt}]') | Out-Null
}

$tgArn = Invoke-Aws @('elbv2','describe-target-groups','--query','TargetGroups[?TargetGroupName==`ia-autoscaler-tg`].TargetGroupArn | [0]','--output','text')
if ($tgArn -eq 'None') {
  $tgArn = Invoke-Aws @('elbv2','create-target-group','--name','ia-autoscaler-tg','--protocol','HTTP','--port','8080','--vpc-id',$VpcId,'--target-type','instance','--health-check-path','/health','--health-check-interval-seconds','15','--healthy-threshold-count','2','--unhealthy-threshold-count','2','--tags','Key=project,Value=ia-autoscaler','Key=Name,Value=ia-autoscaler-tg','--query','TargetGroups[0].TargetGroupArn','--output','text')
}
$albArgs = @('elbv2','create-load-balancer','--name','ia-autoscaler-alb','--subnets') + $SubnetIds + @('--security-groups',$sgId,'--scheme','internet-facing','--type','application','--ip-address-type','ipv4','--tags','Key=project,Value=ia-autoscaler','Key=Name,Value=ia-autoscaler-alb','--query','LoadBalancers[0].LoadBalancerArn','--output','text')
$albArn = Invoke-Aws $albArgs
Invoke-Aws @('elbv2','wait','load-balancer-available','--load-balancer-arns',$albArn) | Out-Null
Invoke-Aws @('elbv2','create-listener','--load-balancer-arn',$albArn,'--protocol','HTTP','--port','80','--default-actions',("Type=forward,TargetGroupArn={0}" -f $tgArn)) | Out-Null

$subnetList = $SubnetIds -join ','
Invoke-Aws @('autoscaling','create-auto-scaling-group','--auto-scaling-group-name','ia-autoscaler-asg','--launch-template','LaunchTemplateName=ia-autoscaler-lt,Version=$Latest','--min-size','1','--max-size','6','--desired-capacity','1','--vpc-zone-identifier',$subnetList,'--target-group-arns',$tgArn,'--health-check-type','ELB','--health-check-grace-period','180','--tags','ResourceId=ia-autoscaler-asg,ResourceType=auto-scaling-group,Key=project,Value=ia-autoscaler,PropagateAtLaunch=true','ResourceId=ia-autoscaler-asg,ResourceType=auto-scaling-group,Key=Name,Value=ia-autoscaler-instance,PropagateAtLaunch=true') | Out-Null

Invoke-Aws @('autoscaling','wait','group-in-service','--auto-scaling-group-names','ia-autoscaler-asg') | Out-Null
Invoke-Aws @('elbv2','wait','target-in-service','--target-group-arn',$tgArn) | Out-Null
$dns = Invoke-Aws @('elbv2','describe-load-balancers','--load-balancer-arns',$albArn,'--query','LoadBalancers[0].DNSName','--output','text')
Write-Output "Endpoint: http://$dns/health"
