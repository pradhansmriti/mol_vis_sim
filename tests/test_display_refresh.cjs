// Sparse channels must retain their own simulation timestamps and values.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('function renderMeasurements(');
const end=source.indexOf('\nfunction updateReadinessLength',start);
const elements={'coordinate-status':{}};
for(const channel of ['energy','temperature']) elements['latest-'+channel]={children:[{}, {}, {}]};
const plots={};
const context=vm.createContext({$:id=>elements[id],coordinateStructure:null,
  draw:()=>{},drawMeasurementChart:(id,samples)=>plots[id]=samples,measuredNumber:String});
vm.runInContext(source.slice(start,end),context);
const samples=[
 {stage:'dynamics',step:10,time_ps:.02,temperature_k:300},
 {stage:'dynamics',step:12,time_ps:.024,potential_energy_kj_mol:-10,kinetic_energy_kj_mol:3,total_energy_kj_mol:-7}
];
context.renderMeasurements({id:'example',settings:{temperature_k:300},samples});
assert.equal(elements['latest-temperature'].children[1].textContent,'0.02');
assert.equal(elements['latest-temperature'].children[2].textContent,'300 K');
assert.equal(elements['latest-energy'].children[1].textContent,'0.024');
assert.match(elements['latest-energy'].children[2].textContent,/Potential -10/);
assert.equal(samples.length,2);
console.log('Independent channel timestamps and sparse measurement rendering passed.');

// Reconnecting must show the frozen run settings rather than browser defaults.
const legend={}; elements['display-frequency']={querySelector:()=>legend};
for(const channel of ['coordinates','energy','temperature']) elements[channel+'-interval']={value:10};
elements.timestep={value:2}; elements['readiness-steps']={value:100}; let displayedTimestep;
context.updateReadinessLength=()=>{};
context.updateOutputSpacing=value=>displayedTimestep=value;
const helperStart=source.indexOf('function showRunOutputIntervals(');
const helperEnd=source.indexOf('\nasync function startRunMonitor',helperStart);
vm.runInContext(source.slice(helperStart,helperEnd),context);
context.showRunOutputIntervals({status:'running',settings:{coordinates_interval_steps:1,energy_interval_steps:2,temperature_interval_steps:3,timestep_fs:.1,dynamics_steps:1000}});
assert.deepEqual(['coordinates','energy','temperature'].map(c=>elements[c+'-interval'].value),[1,2,3]);
assert.equal(elements['readiness-steps'].value,1000);
assert.equal(displayedTimestep,.1);assert.equal(legend.textContent,'Output intervals · current run');
context.showRunOutputIntervals({status:'completed',settings:{timestep_fs:.1}});
assert.equal(displayedTimestep,2);assert.equal(legend.textContent,'Output intervals · next run');
console.log('Reconnect restores frozen intervals and simulated-time spacing.');
