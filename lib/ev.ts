import { z } from 'zod';
import fixtures from '../data/stations.json';
import model from '../data/model.json';
export const ORIGIN = {lat:12.9716,lng:77.5946};
export const profiles=[{id:'compact',name:'Compact EV',capacity:40,ac:7.2,dc:50,consumption:145},{id:'crossover',name:'Long-range crossover',capacity:60,ac:11,dc:120,consumption:175},{id:'city',name:'City EV',capacity:24,ac:7.2,dc:30,consumption:120}];
export const inputSchema=z.object({mode:z.enum(['demo','connected']).default('demo'),lat:z.number().min(-90).max(90).default(ORIGIN.lat),lng:z.number().min(-180).max(180).default(ORIGIN.lng),soc:z.number().min(0).max(100).default(28),reserve:z.number().min(0).max(50).default(10),target:z.number().min(1).max(100).default(80),capacity:z.number().positive().max(250).default(60),ac:z.number().positive().max(50).default(11),dc:z.number().positive().max(500).default(120),consumption:z.number().min(50).max(600).default(175),connector:z.enum(['CCS2','Type 2','CHAdeMO']).default('CCS2'),preset:z.enum(['balanced','fast','cost']).default('balanced'),radius:z.number().min(1).max(50).default(15),minPower:z.number().min(0).max(500).default(0),complete:z.boolean().default(false),hour:z.number().int().min(0).max(23).default(14),day:z.number().int().min(0).max(6).default(2)});
export type Inputs=z.infer<typeof inputSchema>;
export type Station={id:string;name:string;area:string;lat:number;lng:number;power:number|null;connector:string;count:number|null;price:number|null;access:string;status:string;category:number;distance:number|null;minutes:number|null;geometry?:[number,number][];attribution?:string;tariff?:string;fetched_at?:string;updated_at?:string;route_source?:string;closed?:boolean};
export type Ranked=Station & {eligibility:'eligible'|'excluded'|'verify';reasons:string[];arrival:number|null;energy:number|null;wait:number|null;charge:number|null;cost:number|null;score:number;components:number[];coverage:number;wait_source:string;straight:number};
export type Results={stations:Ranked[];weights:number[];budget:number;range:number;mode:string;timestamp:string;model_version:string;message?:string;stale?:boolean};
export const weights={balanced:[.30,.25,.20,.15,.10],fast:[.40,.30,.20,.05,.05],cost:[.15,.10,.15,.50,.10]};
export const clamp=(n:number,a=0,b=1)=>Math.min(b,Math.max(a,n));
export const round=(n:number,d=1)=>Math.floor(n*10**d+.5+1e-8)/10**d;
export function km(a:{lat:number;lng:number},b:{lat:number;lng:number}){const r=Math.PI/180;const p=Math.sin((b.lat-a.lat)*r/2)**2+Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.sin((b.lng-a.lng)*r/2)**2;return 6371*2*Math.atan2(Math.sqrt(p),Math.sqrt(1-p));}
export function waitPredict(hour:number,day:number,count:number,power:number,category:number){const x=[hour,day,count,power,category];if(model.selected!=='tree')return (model.baseline as Record<string,number>)[`${hour}-${day}`]??0;let i=0;while(model.tree.left[i]!==-1)i=x[model.tree.feature[i]]<=model.tree.threshold[i]?model.tree.left[i]:model.tree.right[i];return Math.max(0,model.tree.value[i]);}
export function physics(distance:number,speed:number,grade=0,aux=1.2){const v=speed/3.6;const rolling=1800*9.81*.012;const aero=.5*1.225*.65*v*v;const gravity=1800*9.81*grade/100;const wheel=rolling+aero+gravity;const traction=wheel>=0?wheel/.9:wheel*.6;return Math.max(0,(traction*distance*1000/3600000)+aux*distance/speed);}
export function demoStations(p:Inputs):Station[]{return fixtures.map(s=>({...s,route_source:'synthetic route fixture',fetched_at:new Date().toISOString(),...(km(p,ORIGIN)>.3?{distance:null,minutes:null}:{}),geometry:km(p,ORIGIN)<=.3?[[p.lat,p.lng],[p.lat,s.lng],[s.lat,s.lng]] as [number,number][]:undefined}));}
export function rank(p:Inputs,stations:Station[]):Results{const w=weights[p.preset];const budget=p.capacity*(p.soc-p.reserve)/100;const ranked=stations.filter(s=>km(p,s)<=p.radius&&(s.power??0)>=p.minPower&&(!p.complete||(s.price!==null&&s.power!==null))).map(s=>{const reasons:string[]=[];let eligibility:Ranked['eligibility']='eligible';const exclude=(r:string)=>{eligibility='excluded';reasons.push(r)};const verify=(r:string)=>{if(eligibility==='eligible')eligibility='verify';reasons.push(r)};
if(s.connector==='Unknown')verify('Connector needs verification');else if(s.connector!==p.connector)exclude('Different connector');
if(s.status==='offline')exclude('Reported unavailable');else if(s.status!=='operational')verify('Operational status unknown');
if(s.access==='private')exclude('Private access');else if(s.access!=='public')verify('Access needs verification');
if(s.closed)exclude('Closed at arrival');
if(s.distance===null||s.minutes===null)verify('Reachability unverified');
const energy=s.distance!==null?round((s.distance*p.consumption/1000+1.2*(s.minutes??0)/60)*1.15,3):null;
const arrival=energy!==null?round(p.soc-energy/p.capacity*100):null;
if(budget<=0)exclude('Battery at or below reserve');else if(energy!==null&&energy>budget)exclude('Below arrival reserve');
const totalMinutes=p.hour*60+(s.minutes??0);const hour=Math.floor(totalMinutes/60)%24;const day=(p.day+Math.floor(totalMinutes/1440))%7;
const wait=s.count!==null&&s.power!==null?round(waitPredict(hour,day,s.count,s.power,s.category)):null;
const delivered=arrival!==null?Math.max(0,p.target-arrival)*p.capacity/100:null;
const effective=s.power!==null?Math.min(s.power,s.connector==='Type 2'?p.ac:p.dc):null;
const charge=effective&&delivered!==null?round(delivered/(effective*.8)*60):null;
const cost=delivered!==null&&s.price!==null?Math.round(delivered/0.9*s.price):null;
const components=[s.minutes!==null?clamp(1-s.minutes/60):.5,wait!==null?clamp(1-wait/60):.5,charge!==null?clamp(1-charge/120):.5,cost!==null?clamp(1-cost/1500):.5,arrival!==null?clamp((arrival-p.reserve)/30):.5];
return {...s,eligibility,reasons,energy,arrival,wait,charge,cost,components,score:round(100*components.reduce((a,c,i)=>a+c*w[i],0)),coverage:[s.minutes,wait,charge,cost,arrival].filter(v=>v!==null).length,wait_source:'Synthetic-data model',straight:round(km(p,s))} as Ranked;});
ranked.sort((a,b)=>({eligible:0,verify:1,excluded:2}[a.eligibility]-{eligible:0,verify:1,excluded:2}[b.eligibility])||b.score-a.score||a.id.localeCompare(b.id));return {stations:ranked,weights:w,budget:round(Math.max(0,budget),2),range:Math.floor(Math.max(0,budget)/(p.consumption/1000)*.85),mode:p.mode,timestamp:new Date().toISOString(),model_version:model.version};}
