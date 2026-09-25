import unittest,os,tempfile
os.environ['CHARGEWISE_DB']=os.path.join(tempfile.mkdtemp(),'test.db')
from fastapi.testclient import TestClient
from backend.core import Inputs,demo_stations,rank,physics,predict
from backend.main import app
class CoreTests(unittest.TestCase):
 def test_eligibility(self):
  p=Inputs();r=rank(p,demo_stations(p));eligible=[s for s in r['stations'] if s['eligibility']=='eligible']
  self.assertTrue(eligible);self.assertTrue(all(s['connector']==p.connector and s['arrival']>=p.reserve for s in eligible))
  self.assertNotEqual(eligible[0]['id'],'demo-1')
 def test_no_reserve(self):
  for soc in (0,5,10):
   p=Inputs(soc=soc);self.assertFalse(any(s['eligibility']=='eligible' for s in rank(p,demo_stations(p))['stations']))
 def test_missing_price(self):
  p=Inputs();s=next(s for s in rank(p,demo_stations(p))['stations'] if s['id']=='demo-5');self.assertIsNone(s['cost']);self.assertEqual(s['components'][3],.5)
 def test_unknown_route(self):
  p=Inputs(lat=12.98);r=rank(p,demo_stations(p));self.assertFalse(any(s['eligibility']=='eligible' for s in r['stations']))
 def test_private_offline(self):
  p=Inputs();r=rank(p,demo_stations(p));self.assertTrue(all(s['eligibility']=='excluded' for s in r['stations'] if s['id'] in ('demo-6','demo-7')))
 def test_closed(self):
  p=Inputs();s=demo_stations(p)[1];s['closed']=True;self.assertEqual(rank(p,[s])['stations'][0]['eligibility'],'excluded')
 def test_power_limit(self):
  p=Inputs(dc=20);s=rank(p,[demo_stations(p)[1]])['stations'][0];self.assertGreater(s['charge'],100)
 def test_ac_limit(self):
  p=Inputs(connector='Type 2',ac=7.2);s=rank(p,[demo_stations(p)[0]])['stations'][0];self.assertGreater(s['charge'],300)
 def test_physics(self):
  self.assertAlmostEqual(physics(10,50)*2,physics(20,50));self.assertGreater(physics(10,100),physics(10,50));self.assertGreaterEqual(physics(10,50,-15),0)
 def test_repeatable(self):
  self.assertEqual(predict(18,2,4,60,1),predict(18,2,4,60,1))
class APITests(unittest.TestCase):
 def setUp(self):self.c=TestClient(app)
 def test_invalid(self):
  for body in ({'soc':101},{'capacity':0},{'lat':91},{'dc':0}):self.assertEqual(self.c.post('/api/recommendations',json=body).status_code,422)
 def test_missing_key(self):
  old=os.environ.pop('OCM_API_KEY',None)
  try:self.assertEqual(self.c.post('/api/recommendations',json={'mode':'connected'}).status_code,503)
  finally:
   if old:os.environ['OCM_API_KEY']=old
 def test_complete_journey(self):
  r=self.c.post('/api/recommendations',json={});self.assertEqual(r.status_code,200);data=r.json();best=data['stations'][0];self.assertEqual(best['eligibility'],'eligible');e=self.c.post('/api/energy-scenarios',json={'distance':best['distance']});self.assertEqual(len(e.json()['scenarios']),8)
 def test_profile(self):
  r=self.c.post('/api/vehicle-profiles',json={'name':'Test EV','capacity':60,'ac':11,'dc':120,'consumption':175});self.assertEqual(r.status_code,200);self.assertIn(r.json()['id'],[v['id'] for v in self.c.get('/api/vehicle-profiles').json()])
 def test_simulation(self):
  id=self.c.post('/api/simulations',json={}).json()['simulation_id'];self.assertEqual(self.c.get('/api/simulations/'+id+'/telemetry').json()['source'],'simulated')
if __name__=='__main__':unittest.main()
