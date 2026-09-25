"""Reproducible synthetic queue experiment; no claims of real-world accuracy."""
import heapq, json, math
from pathlib import Path
import numpy as np
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import mean_absolute_error

ROOT=Path(__file__).resolve().parents[1]
rng=np.random.default_rng(42)
rows=[]
# Each arrival sees the earliest free connector. Distinct held-out stations use
# the same generator family; this is explicitly a synthetic generalization test.
for station in range(12):
    count=2+station%4
    power=[22,60,120][station%3]
    category=station%3
    heap=[0.0]*count
    heapq.heapify(heap)
    for day in range(70):
        for hour in range(24):
            rush=1.8 if hour in range(8,11) or hour in range(17,21) else 0.6
            demand=count*(60/(22 if power>22 else 40))*(0.30+category*0.05)*rush*(1.15 if day%7>=5 else 1)
            arrivals=sorted(rng.uniform(0,60,rng.poisson(demand)))
            for offset in arrivals:
                now=day*1440+hour*60+offset
                free=heapq.heappop(heap)
                wait=max(0,free-now)
                service=float(np.clip(rng.lognormal(math.log(22 if power>22 else 40),.35),8,100))
                heapq.heappush(heap,max(now,free)+service)
                rows.append([station,day,hour,day%7,count,power,category,wait])
a=np.array(rows)
train=a[(a[:,0]<10)&(a[:,1]<49)]
val=a[(a[:,0]<10)&(a[:,1]>=49)&(a[:,1]<59)]
test=a[(a[:,0]<10)&(a[:,1]>=59)]
hold=a[(a[:,0]>=10)&(a[:,1]>=59)]
# The baseline only uses hour/day, fitted on the training interval.
base={f'{h}-{d}':float(np.mean(train[(train[:,2]==h)&(train[:,3]==d),7])) for h in range(24) for d in range(7)}
def baseline(ds): return np.array([base[f'{int(r[2])}-{int(r[3])}'] for r in ds])
def score(m,ds): return float(mean_absolute_error(ds[:,7],m.predict(ds[:,2:7])))
candidates=[]
for depth in (4,6,8):
    m=DecisionTreeRegressor(max_depth=depth,min_samples_leaf=40,random_state=42).fit(train[:,2:7],train[:,7])
    candidates.append((score(m,val),m))
_,model=min(candidates,key=lambda x:x[0])
use_tree=score(model,val)<float(mean_absolute_error(val[:,7],baseline(val)))
t=model.tree_
artifact={'version':'synthetic-queue-v1','seed':42,'feature_names':['hour','day_of_week','connector_count','power_kw','category'],'selected':'tree' if use_tree else 'hour_day_baseline','baseline':base,'tree':{'left':t.children_left.tolist(),'right':t.children_right.tolist(),'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),'value':t.value[:,0,0].tolist()}}
metrics={'version':artifact['version'],'provenance':'Synthetic queue sessions; not validated against real charging stations.','seed':42,'rows':len(rows),'train_rows':len(train),'validation_rows':len(val),'test_rows':len(test),'holdout_rows':len(hold),'split':'Days 1–49 train; 50–59 validation; 60–70 test. Stations 11–12 held out.','selected':artifact['selected'],'tree_depth':model.get_depth(),'test_mae_minutes':round(score(model,test),2),'baseline_mae_minutes':round(float(mean_absolute_error(test[:,7],baseline(test))),2),'station_holdout_mae_minutes':round(score(model,hold),2),'regime_mae':{label:round(score(model,ds),2) for label,ds in [('busy_hours',test[np.isin(test[:,2],[8,9,10,17,18,19,20])]),('other_hours',test[~np.isin(test[:,2],[8,9,10,17,18,19,20])])]},'limitations':['Synthetic performance is not real-world accuracy.','Unobserved current queues cause irreducible uncertainty.','No real occupancy or traffic feeds.']}
(ROOT/'data').mkdir(exist_ok=True)
(ROOT/'data/model.json').write_text(json.dumps(artifact,separators=(',',':')))
(ROOT/'data/metrics.json').write_text(json.dumps(metrics,indent=2))
print(json.dumps(metrics,indent=2))
