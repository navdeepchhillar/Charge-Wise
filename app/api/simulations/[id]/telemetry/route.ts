import {readSimulation} from '@/lib/simulation';
import {pythonProxy} from '@/lib/python-proxy';
export async function GET(req:Request,{params}:{params:Promise<{id:string}>}){const {id}=await params;const proxy=await pythonProxy(`simulations/${encodeURIComponent(id)}/telemetry`);if(proxy)return proxy;try{return Response.json(readSimulation(id));}catch{return Response.json({error:'Simulation expired or invalid'},{status:404});}}
