"""Local FastAPI backend. Run: python -m uvicorn backend.main:app --port 8000"""
import json,os,sqlite3,uuid,time,asyncio,re
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field
import httpx
from .core import Inputs,ROOT,demo_stations,rank,physics,km,timestamp
app=FastAPI(title='Chargewise API',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('FRONTEND_ORIGINS','http://localhost:5173,http://localhost:4173').split(','),allow_methods=['GET','POST'],allow_headers=['Content-Type'])
DB=Path(os.getenv('CHARGEWISE_DB',str(ROOT/'backend/state/chargewise.db')));DB.parent.mkdir(parents=True,exist_ok=True)
def db():
    conn=sqlite3.connect(DB);conn.execute('CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, data TEXT)');conn.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at REAL, data TEXT)');return conn
PROFILES=[dict(id='compact',name='Compact EV',capacity=40,ac=7.2,dc=50,consumption=145),dict(id='crossover',name='Long-range crossover',capacity=60,ac=11,dc=120,consumption=175),dict(id='city',name='City EV',capacity=24,ac=7.2,dc=30,consumption=120)]
@app.middleware('http')
async def limits(req:Request,call_next):
    if req.method=='POST':
        body=await req.body()
        if len(body)>12000:return JSONResponse({'error':'Request too large'},status_code=413)
    return await call_next(req)
@app.exception_handler(HTTPException)
async def errors(req,exc):return JSONResponse({'error':exc.detail},status_code=exc.status_code)
@app.get('/api/health')
def health():return dict(status='ok',station_configured=bool(os.getenv('OCM_API_KEY')),routing_configured=bool(os.getenv('ORS_API_KEY')),model_version='synthetic-queue-v1',runtime='python')
@app.get('/api/vehicle-profiles')
def profiles():
    with db() as conn:return PROFILES+[json.loads(row[0]) for row in conn.execute('SELECT data FROM profiles')]
class Profile(BaseModel):
    name:str=Field(min_length=1,max_length=80)
    capacity:float=Field(gt=0,le=250)
    ac:float=Field(gt=0,le=50)
    dc:float=Field(gt=0,le=500)
    consumption:float=Field(ge=50,le=600)
    connector:str='CCS2'
@app.post('/api/vehicle-profiles')
def save_profile(p:Profile):
    item=p.model_dump();item['id']=str(uuid.uuid4())
    with db() as conn:conn.execute('INSERT INTO profiles VALUES (?,?)',(item['id'],json.dumps(item)))
    return item
async def request_json(client,method,url,**kwargs):
    for attempt in range(2):
        try:
            r=await client.request(method,url,timeout=9,**kwargs);r.raise_for_status();return r.json()
        except (httpx.HTTPError,ValueError):
            if attempt:raise HTTPException(503,'Station or routing provider is unavailable. Try again later.')
            await asyncio.sleep(.25)
async def connected(p):
    key=os.getenv('OCM_API_KEY')
    if not key:raise HTTPException(503,'Station connection is not configured. Demo mode remains available.')
    ck=f'{p.lat:.2f},{p.lng:.2f},{p.radius}'
    with db() as conn:saved=conn.execute('SELECT at,data FROM cache WHERE key=?',(ck,)).fetchone()
    stale=False
    async with httpx.AsyncClient() as client:
        if saved and time.time()-saved[0]<900:stations=json.loads(saved[1])
        else:
            try:
                data=await request_json(client,'GET','https://api.openchargemap.io/v3/poi/',headers={'X-API-Key':key},params=dict(output='json',latitude=p.lat,longitude=p.lng,distance=p.radius,distanceunit='KM',maxresults=30,compact='false',verbose='false'))
                if not isinstance(data,list):raise HTTPException(503,'Malformed station response')
                stations=[]
                for raw in data:
                    a=raw.get('AddressInfo') or {}
                    if not isinstance(a.get('Latitude'),(int,float)) or not isinstance(a.get('Longitude'),(int,float)):continue
                    for idx,c in enumerate(raw.get('Connections') or [{}]):
                        title=(c.get('ConnectionType') or {}).get('Title','');usage=(raw.get('UsageType') or {}).get('Title','');op=(raw.get('StatusType') or {}).get('IsOperational')
                        connector='CCS2' if re.search(r'CCS.*Type\s*2|Combo\s*2|CCS2',title,re.I) else 'CHAdeMO' if re.search('CHAdeMO',title,re.I) else 'Type 2' if re.search('Type 2|Mennekes',title,re.I) else 'Unknown'
                        stations.append(dict(id=f"ocm-{raw.get('ID')}-{idx}",name=a.get('Title') or 'Charging station',area=a.get('AddressLine1') or a.get('Town') or '',lat=a['Latitude'],lng=a['Longitude'],power=c.get('PowerKW'),connector=connector,count=c.get('Quantity'),price=None,tariff=raw.get('UsageCost') or 'Unknown',access='private' if re.search('private|restricted',usage,re.I) else 'public' if re.search('^public',usage,re.I) else 'unknown',status='operational' if op is True else 'offline' if op is False else 'unknown',category=0,distance=None,minutes=None,updated_at=raw.get('DateLastStatusUpdate'),fetched_at=timestamp(),attribution=(raw.get('DataProvider') or {}).get('Title','Open Charge Map')))
                with db() as conn:
                    conn.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(ck,time.time(),json.dumps(stations)))
                    conn.execute('DELETE FROM cache WHERE at < ?',(time.time()-86400,))
            except HTTPException:
                if not saved:raise
                stations=json.loads(saved[1]);stale=True
        if os.getenv('ORS_API_KEY'):
            for s in sorted(stations,key=lambda s:km(p.model_dump(),s))[:8]:
                try:
                    data=await request_json(client,'POST','https://api.openrouteservice.org/v2/directions/driving-car/geojson',headers={'Authorization':os.environ['ORS_API_KEY']},json={'coordinates':[[p.lng,p.lat],[s['lng'],s['lat']]]})
                    f=data['features'][0];summary=f['properties']['summary'];s.update(distance=summary['distance']/1000,minutes=summary['duration']/60,geometry=[[c[1],c[0]] for c in f['geometry']['coordinates']],route_source='OpenRouteService')
                except (HTTPException,KeyError,IndexError,TypeError):pass
    return stations,stale
@app.get('/api/stations')
async def stations(mode:str='demo',lat:float=12.9716,lng:float=77.5946,radius:float=15):
    p=Inputs(mode=mode,lat=lat,lng=lng,radius=radius)
    data,stale=(demo_stations(p),False) if mode=='demo' else await connected(p)
    return dict(stations=data,stale=stale)
@app.post('/api/recommendations')
async def recommendations(p:Inputs):
    data,stale=(demo_stations(p),False) if p.mode=='demo' else await connected(p)
    return {**rank(p,data),'stale':stale}
class Scenario(Inputs):distance:float=Field(gt=0,le=500)
@app.post('/api/energy-scenarios')
def energy(p:Scenario):
    out=[]
    for speed in (30,40,50,60,70,80,90,100):
        e=physics(p.distance,speed)*1.15;arrival=p.soc-e/p.capacity*100
        out.append(dict(speed=speed,energy=round(e,2),arrival=round(arrival,1),minutes=round(p.distance/speed*60,1),feasible=arrival>=p.reserve,baseline=round(p.distance*p.consumption/1000,2)))
    return dict(scenarios=out,assumptions='Generic 1,800 kg vehicle, flat route, 1.2 kW auxiliary load, 15% margin. Speed limits are unavailable: comparison scenarios, not driving recommendations.')
@app.get('/api/model-metrics')
def metrics():return json.loads((ROOT/'data/metrics.json').read_text())
SIMS={}
@app.post('/api/simulations')
def simulation(p:Inputs):
    if len(SIMS)>100:SIMS.clear()
    id=str(uuid.uuid4());SIMS[id]=(time.monotonic(),p)
    return dict(simulation_id=id,source='simulated')
@app.get('/api/simulations/{id}/telemetry')
def telemetry(id:str):
    if id not in SIMS:raise HTTPException(404,'Simulation not found or expired')
    start,p=SIMS[id];elapsed=time.monotonic()-start
    return dict(timestamp=timestamp(),latitude=p.lat,longitude=p.lng,soc_percent=round(max(0,p.soc-int(elapsed//4)*.1),1),speed_kmh=30,source='simulated')
