import {startSimulation} from '@/lib/simulation';
import {pythonProxy} from '@/lib/python-proxy';
export async function POST(req:Request){const proxy=await pythonProxy('simulations',req.clone());if(proxy)return proxy;try{return Response.json(startSimulation(await req.json()));}catch{return Response.json({error:'Invalid simulation inputs'},{status:422});}}
