// Sparse channels must retain their own simulation timestamps and values.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
const start=source.indexOf('function renderMeasurements(');
const end=source.indexOf('\nfunction updateOutputSpacing',start);
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
