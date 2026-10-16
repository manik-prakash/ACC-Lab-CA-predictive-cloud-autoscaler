"""Run stepped HTTP load tests and save observed client-side latency/throughput."""
import argparse, csv, statistics, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

def percentile(values, q):
    if not values: return None
    values=sorted(values); return values[min(len(values)-1, int(q*(len(values)-1)))]

def stage(endpoint, workers, seconds, units):
    until=time.monotonic()+seconds; samples=[]
    def worker():
        local=[]
        while time.monotonic()<until:
            start=time.perf_counter()
            try:
                with urlopen(f'{endpoint}/work?units={units}', timeout=20) as response:
                    response.read(); local.append((True,(time.perf_counter()-start)*1000))
            except Exception:
                local.append((False,(time.perf_counter()-start)*1000))
        return local
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for group in pool.map(lambda _: worker(), range(workers)): samples.extend(group)
    ok=[lat for success,lat in samples if success]
    return dict(workers=workers, requests=len(samples), successes=len(ok), failures=len(samples)-len(ok), rps=len(ok)/seconds, p50_ms=percentile(ok,.5), p95_ms=percentile(ok,.95), mean_ms=statistics.mean(ok) if ok else None)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--endpoint',required=True); p.add_argument('--seconds',type=int,default=60); p.add_argument('--units',type=int,default=500000); p.add_argument('--repeats',type=int,default=3); p.add_argument('--out',default='results/calibration_client.csv'); args=p.parse_args()
    levels=(1,2,4,6,8); rows=[]
    for repeat in range(1,args.repeats+1):
        for workers in levels:
            print(f'repeat={repeat} workers={workers}',flush=True)
            row=stage(args.endpoint.rstrip('/'),workers,args.seconds,args.units); row.update(repeat=repeat,units=args.units); rows.append(row); print(row,flush=True)
    path=Path(args.out); path.parent.mkdir(exist_ok=True)
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
