"""Pure recommendation functions. JSON model is shared with the hosted adapter."""
import json,math
from pathlib import Path
from datetime import datetime,timezone
from typing import Literal
from pydantic import BaseModel,Field
ROOT=Path(__file__).resolve().parents[1]
FIXTURES=json.loads((ROOT/'data/stations.json').read_text())
MODEL=json.loads((ROOT/'data/model.json').read_text())
ORIGIN={'lat':12.9716,'lng':77.5946}
WEIGHTS={'balanced':[.3,.25,.2,.15,.1],'fast':[.4,.3,.2,.05,.05],'cost':[.15,.1,.15,.5,.1]}
class Inputs(BaseModel):
    mode:Literal['demo','connected']='demo'
    lat:float=Field(12.9716,ge=-90,le=90)
    lng:float=Field(77.5946,ge=-180,le=180)
    soc:float=Field(28,ge=0,le=100)
    reserve:float=Field(10,ge=0,le=50)
    target:float=Field(80,gt=0,le=100)
    capacity:float=Field(60,gt=0,le=250)
    ac:float=Field(11,gt=0,le=50)
    dc:float=Field(120,gt=0,le=500)
    consumption:float=Field(175,ge=50,le=600)
    connector:Literal['CCS2','Type 2','CHAdeMO']='CCS2'
    preset:Literal['balanced','fast','cost']='balanced'
    radius:float=Field(15,ge=1,le=50)
    minPower:float=Field(0,ge=0,le=500)
    complete:bool=False
    hour:int=Field(14,ge=0,le=23)
    day:int=Field(2,ge=0,le=6)
def round(n,d=0):return math.floor(n*10**d+.5+1e-8)/10**d
def timestamp():return datetime.now(timezone.utc).isoformat()
def clamp(n):return min(1,max(0,n))
def km(a,b):
    r=math.pi/180
    p=math.sin((b['lat']-a['lat'])*r/2)**2+math.cos(a['lat']*r)*math.cos(b['lat']*r)*math.sin((b['lng']-a['lng'])*r/2)**2
    return 6371*2*math.atan2(math.sqrt(p),math.sqrt(1-p))
def predict(hour,day,count,power,category):
    if MODEL['selected']!='tree':return MODEL['baseline'][f'{hour}-{day}']
    x=[hour,day,count,power,category];i=0;t=MODEL['tree']
    while t['left'][i]!=-1:i=t['left'][i] if x[t['feature'][i]]<=t['threshold'][i] else t['right'][i]
    return max(0,t['value'][i])
def physics(distance,speed,grade=0,aux=1.2):
    v=speed/3.6
    wheel=1800*9.81*.012+.5*1.225*.65*v*v+1800*9.81*grade/100
    traction=wheel/.9 if wheel>=0 else wheel*.6
    return max(0,traction*distance*1000/3600000+aux*distance/speed)
def demo_stations(p):
    result=json.loads(json.dumps(FIXTURES));origin=p.model_dump()
    for s in result:
        s.update(route_source='synthetic route fixture',fetched_at=timestamp())
        if km(origin,ORIGIN)>.3:s.update(distance=None,minutes=None)
        else:s['geometry']=[[p.lat,p.lng],[p.lat,s['lng']],[s['lat'],s['lng']]]
    return result

def rank(p,stations):
    budget=p.capacity*(p.soc-p.reserve)/100;out=[];w=WEIGHTS[p.preset]
    for original in stations:
        s=dict(original)
        if km(p.model_dump(),s)>p.radius or (s['power'] or 0)<p.minPower or (p.complete and (s['price'] is None or s['power'] is None)):continue
        reasons=[];excluded=False;verify=False
        if s['connector']=='Unknown':reasons.append('Connector needs verification');verify=True
        elif s['connector']!=p.connector:reasons.append('Different connector');excluded=True
        if s['status']=='offline':reasons.append('Reported unavailable');excluded=True
        elif s['status']!='operational':reasons.append('Operational status unknown');verify=True
        if s['access']=='private':reasons.append('Private access');excluded=True
        elif s['access']!='public':reasons.append('Access needs verification');verify=True
        if s.get('closed'):reasons.append('Closed at arrival');excluded=True
        if s['distance'] is None or s['minutes'] is None:reasons.append('Reachability unverified');verify=True
        energy=round((s['distance']*p.consumption/1000+1.2*(s['minutes'] or 0)/60)*1.15,3) if s['distance'] is not None else None
        arrival=round(p.soc-energy/p.capacity*100,1) if energy is not None else None
        if budget<=0:reasons.append('Battery at or below reserve');excluded=True
        elif energy is not None and energy>budget:reasons.append('Below arrival reserve');excluded=True
        total=p.hour*60+(s['minutes'] or 0);hour=int(total//60)%24;day=(p.day+int(total//1440))%7
        wait=round(predict(hour,day,s['count'],s['power'],s['category']),1) if s['count'] is not None and s['power'] is not None else None
        delivered=max(0,p.target-arrival)*p.capacity/100 if arrival is not None else None
        effective=min(s['power'],p.ac if s['connector']=='Type 2' else p.dc) if s['power'] is not None else None
        charge=round(delivered/(effective*.8)*60,1) if effective and delivered is not None else None
        cost=math.floor(delivered/.9*s['price']+.5) if delivered is not None and s['price'] is not None else None
        components=[clamp(1-s['minutes']/60) if s['minutes'] is not None else .5,clamp(1-wait/60) if wait is not None else .5,clamp(1-charge/120) if charge is not None else .5,clamp(1-cost/1500) if cost is not None else .5,clamp((arrival-p.reserve)/30) if arrival is not None else .5]
        s.update(eligibility='excluded' if excluded else 'verify' if verify else 'eligible',reasons=reasons,energy=energy,arrival=arrival,wait=wait,charge=charge,cost=cost,components=components,score=round(sum(a*b for a,b in zip(w,components))*100,1),coverage=sum(x is not None for x in [s['minutes'],wait,charge,cost,arrival]),wait_source='Synthetic-data model',straight=round(km(p.model_dump(),s),1));out.append(s)
    out.sort(key=lambda s:({'eligible':0,'verify':1,'excluded':2}[s['eligibility']],-s['score'],s['id']))
    return dict(stations=out,weights=w,budget=round(max(0,budget),2),range=math.floor(max(0,budget)/(p.consumption/1000)*.85),mode=p.mode,timestamp=timestamp(),model_version=MODEL['version'])
