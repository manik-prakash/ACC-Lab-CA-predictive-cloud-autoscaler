"""Small NumPy DQN for the autoscaler simulator; no external ML framework needed."""
import json, random
from pathlib import Path
import numpy as np
from experiment import Env, trace, summary, training_set

def features(state):
    return np.array([state[0]/5, state[1]/4, state[2]/5, state[3]/3], dtype=float)

def train(seed=1, episodes=70):
    rng=np.random.default_rng(seed); py=random.Random(seed)
    w1=rng.normal(0,.15,(4,20)); b1=np.zeros(20); w2=rng.normal(0,.15,(20,3)); b2=np.zeros(3)
    replay=[]; curve=[]; loads=training_set(seed)
    for ep in range(episodes):
        env=Env(loads[ep%len(loads)]); state=env.reset(); total=0.; eps=max(.03,.4*(1-ep/episodes))
        while env.t<len(env.load):
            x=features(state); h=np.maximum(0,x@w1+b1); q=h@w2+b2
            action=py.randrange(3) if py.random()<eps else int(q.argmax())
            next_state,reward,done,_=env.step(action-1); replay.append((x,action,reward,features(next_state),done)); state=next_state; total+=reward
            if len(replay)>=8:
                for x,a,r,nx,d in py.sample(replay,min(8,len(replay))):
                    h=np.maximum(0,x@w1+b1); q=h@w2+b2; nh=np.maximum(0,nx@w1+b1); target=r if d else r+.95*nh.max(); error=q[a]-target
                    gradq=np.zeros(3); gradq[a]=2*error; gw2=np.outer(h,gradq); gb2=gradq; gh=gradq@w2.T; gz=gh*(h>0); w2-=.002*gw2; b2-=.002*gb2; w1-=.002*np.outer(x,gz); b1-=.002*gz
        curve.append(total)
    env=Env(trace('spike',seed=99)); rows=[]
    while env.t<len(env.load):
        x=features(env.state()); a=int((np.maximum(0,x@w1+b1)@w2+b2).argmax()); _,_,_,row=env.step(a-1); rows.append(row)
    return rows,curve

if __name__=='__main__':
    out=Path('results'); out.mkdir(exist_ok=True); all_metrics=[]
    for seed in (1,2,3):
        rows,curve=train(seed); all_metrics.append(summary(f'dqn_seed_{seed}',rows)); np.savetxt(out/f'dqn_curve_seed_{seed}.csv',np.asarray(curve),delimiter=',',header='reward',comments='')
    (out/'dqn_metrics.json').write_text(json.dumps(all_metrics,indent=2)); print(json.dumps(all_metrics,indent=2))
