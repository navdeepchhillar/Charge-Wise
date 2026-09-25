import {inputSchema,demoStations} from '@/lib/ev';
import {connectedStations} from '@/lib/providers';
export async function GET(req:Request){try{const q=new URL(req.url).searchParams;const p=inputSchema.parse({mode:q.get('mode')||'demo',lat:Number(q.get('lat')??12.9716),lng:Number(q.get('lng')??77.5946),radius:Number(q.get('radius')??15)});return Response.json(p.mode==='demo'?{stations:demoStations(p),stale:false}:await connectedStations(p));}catch(e){return Response.json({error:String(e)},{status:503});}}
