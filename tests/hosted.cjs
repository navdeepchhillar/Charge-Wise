// Transpile only pure app modules for Node-based verification without a server.
const ts=require('typescript'),fs=require('fs'),path=require('path'),Module=require('module'),assert=require('assert');
function load(file){const filename=path.resolve(file);const m=new Module(filename,module);m.filename=filename;m.paths=module.paths;const original=m.require.bind(m);m.require=(id)=>id.startsWith('./')&&fs.existsSync(path.resolve(path.dirname(filename),id+'.ts'))?load(path.resolve(path.dirname(filename),id+'.ts')):original(id);m._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,resolveJsonModule:true,target:ts.ScriptTarget.ES2022}}).outputText,filename);return m.exports;}
const core=load('lib/ev.ts'),sim=load('lib/simulation.ts');
const cases=[{}, {soc:5},{connector:'Type 2'},{connector:'CHAdeMO'},{lat:12.98},{complete:true},{hour:18,day:5},{dc:20},{preset:'cost'}];
const results=cases.map(raw=>{const p=core.inputSchema.parse(raw);return {raw,result:core.rank(p,core.demoStations(p))};});
for(const r of results){const p=core.inputSchema.parse(r.raw);assert(r.result.stations.filter(s=>s.eligibility==='eligible').every(s=>s.connector===p.connector&&s.arrival>=p.reserve));}
assert(!results[1].result.stations.some(s=>s.eligibility==='eligible'));
assert(!results[4].result.stations.some(s=>s.eligibility==='eligible'));
assert(!core.inputSchema.safeParse({capacity:0}).success);
assert(!core.inputSchema.safeParse({soc:101}).success);
assert(core.physics(10,100)>core.physics(10,50));
const state=sim.startSimulation({});assert.equal(sim.readSimulation(state.simulation_id).source,'simulated');
console.log(JSON.stringify(results));
