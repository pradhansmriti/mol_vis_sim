const $ = id => document.getElementById(id);
let plan = null, pdb = '', yaw = 0, pitch = 0, zoom = 1, dragging = null, revision = 0, prepared = null, preparing = false, checking = false;
let implicitSalt = '0.2', previousSolvent = 'deferred';
let liveRunning = false, activeRun = null, coordinateStructure = null;

const canvas = $('structure'), ctx = canvas.getContext('2d');
const colors = ['#26785b','#d09843','#5188a3','#9c6d9c'];
function invalidate() {
  coordinateStructure = null;
  revision++;
  plan = null; $('export').disabled = true; $('review').hidden = true;
  $('status').textContent = 'Settings changed'; $('steps').replaceChildren();
  $('events').textContent = 'Propose a workflow to review the current input.';
  $('record').textContent = ''; $('structure-info').textContent = 'No current plan';
  $('compatibility-status').textContent = 'Settings changed. Check OpenMM compatibility for the current inputs.';
  $('environment-downloads').hidden = true;
  draw();
}
const preparationInputs = new Set(['pdb','psf','topologies','parameters','histidine','first-patch','last-patch','hydrogens','confirm-guess','prep-mode']);
function settingsChanged(event) {
  if (preparationInputs.has(event.target.id)) {
    prepared = null; $('prep-downloads').hidden = true;
    $('prep-location').hidden = true;
    $('prep-status').textContent = 'Inputs changed. Prepare the files again.';
  }
  invalidate(); $('propose').disabled = !prepared || preparing;
  refreshEnvironmentButtons();
}
$('plan-form').addEventListener('input', settingsChanged);
$('plan-form').addEventListener('change', settingsChanged);
// Number-input wheel changes are easy to trigger while scrolling the page.
$('plan-form').addEventListener('wheel', event => {
  if (event.target.matches('input[type="number"]')) event.preventDefault();
}, {passive:false});
$('prep-mode').addEventListener('change', () => {
  const generate = $('prep-mode').value === 'generate';
  $('psf-field').hidden = generate; $('psf').disabled = generate; $('psf').required = !generate;
  $('topology-field').hidden = false; $('topologies').disabled = false; $('topologies').required = generate;
  $('generation-options').hidden = !generate;
  $('prepare').textContent = generate ? 'Generate PSF + PDB' : 'Check PSF + PDB pair';
  $('prep-help').textContent = generate ? 'Protein-only selection is applied before psfgen: waters, ions and other non-protein components are excluded and recorded. Choose whether to retain input hydrogens or rebuild them with the selected topology. Resolve chain gaps, alternate positions and custom/disulfide patches first. No minimization or solvation is performed.' : 'Upload files from the same preparation. Atom count and ordered identity must match. Existing coordinates and topology are retained; bonded terms and force-field parameters are not validated.';
});
async function readFile(file, label) {
  if (!file || file.size > 5_000_000) throw Error(`Choose a ${label} file smaller than 5 MB.`);
  return file.text();
}
async function readFiles(id) {
  return Promise.all([...$(id).files].map(async file => ({name:file.name, text:await readFile(file,id)})));
}
$('prepare').addEventListener('click', async () => {
  $('error').textContent = ''; prepared = null; invalidate();
  $('prep-downloads').hidden = true;
  $('prep-location').hidden = true;
  const submittedRevision = revision, mode = $('prep-mode').value;
  const options = {histidine:$('histidine').value,first:$('first-patch').value,last:$('last-patch').value,hydrogens:$('hydrogens').value};
  const confirm_guess = $('confirm-guess').checked;
  preparing = true; $('prepare').disabled = $('propose').disabled = true; refreshEnvironmentButtons();
  $('prep-status').textContent = mode === 'generate' ? 'Generating files…' : 'Checking the pair…';
  try {
    const inputPdb = await readFile($('pdb').files[0], 'PDB');
    const inputPsf = mode === 'upload' ? await readFile($('psf').files[0], 'PSF') : undefined;
    const parameters = await readFiles('parameters');
    const topologies = mode === 'generate' ? await readFiles('topologies') : [];
    if (submittedRevision !== revision) return;
    const response = await fetch('/api/prepare', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({mode,pdb:inputPdb,psf:inputPsf,parameters,topologies,options,confirm_guess})});
    const result = await response.json();
    if (submittedRevision !== revision) return;
    if (!response.ok) throw Error(result.error || 'Preparation failed.');
    prepared = result; pdb = result.pdb; yaw = pitch = 0; zoom = 1;
    $('prep-downloads').hidden = false;
    $('prep-location').textContent = `Saved on the server: ${result.storage.directory} — prepared.pdb, prepared.psf, manifest.json and preparation.zip. Files remain after this page closes. Browser downloads are separate copies saved to your browser’s download location.`;
    $('prep-location').hidden = false;
    $('prep-status').textContent = `${result.structure.atom_count} atoms · pair checked. Review coordinates and force-field parameters before simulation.`;
    $('structure-info').textContent = `${result.structure.atom_count} atoms · ${result.structure.residue_count} residues`;
    $('status').textContent = 'Files prepared';
    $('events').textContent = mode === 'generate' ? 'Standalone psfgen produced a matching PSF/PDB pair. No simulation has run.' : 'Uploaded PSF/PDB pair checked. No atoms or coordinates changed.';
    const selection = result.manifest.details.selection;
    if (selection) {
      const removed = Object.entries(selection.excluded_by_residue).map(([name,counts]) => `${counts.residues} ${name} residues`).join(', ');
      $('events').textContent += ` Protein selection retained ${selection.selected_atoms} input atoms; excluded ${selection.excluded_atoms} atoms${removed ? ` (${removed})` : ''}. Original input: source.pdb; protein selection: protein.pdb; exact psfgen inputs: segments/.`;
    }
    const terminalCheck = result.manifest.details.terminal_coordinate_check;
    const hydrogenHandling = result.manifest.details.hydrogen_handling;
    if (hydrogenHandling) {
      $('events').textContent += hydrogenHandling.mode === 'rebuild' ? ` Removed ${hydrogenHandling.removed_input_atoms} input hydrogens before psfgen rebuilt them from the selected topology and protonation choices.` : ' Retained input hydrogens.';
    }
    if (terminalCheck?.mapped_atoms) {
      $('events').textContent += ` Preserved ${terminalCheck.mapped_atoms} CTER oxygen coordinates using terminal-only O → OT1 / OXT → OT2 mapping.`;
    }
    $('record').textContent = JSON.stringify(result.manifest,null,2); draw();
  } catch(error) {
    if (submittedRevision === revision) { $('error').textContent = error.message; $('prep-status').textContent = 'Preparation needs attention.'; }
  } finally { preparing = false; $('prepare').disabled = false; $('propose').disabled = !prepared; refreshEnvironmentButtons(); }
});

function refreshEnvironmentButtons() {
  const disabled = !prepared || preparing || checking || liveRunning || $('solvent-model').value === 'deferred';
  for(const channel of ['coordinates','energy','temperature']) $(channel+'-interval').disabled=liveRunning || checking;
  $('readiness-steps').disabled=liveRunning || checking;
  $('check-compatibility').disabled = disabled;
  $('test-readiness').disabled = disabled;
  $('propose').disabled = !prepared || preparing || checking || liveRunning;
}

function outputIntervals() {
  return Object.fromEntries(['coordinates','energy','temperature'].map(channel=>[channel+'_interval_steps',Number($(channel+'-interval').value)]));
}
function environmentSettings() {
  if ($('solvent-model').value === 'deferred') return {...outputIntervals(),solvent_model:'deferred',temperature_k:$('temperature').value};
  return {...outputIntervals(),dynamics_steps:Number($('readiness-steps').value),solvent_model:$('solvent-model').value,salt_molar:['obc2','gbn2'].includes($('solvent-model').value) ? $('salt-molar').value : 0,
    padding_nm:$('solvent-model').value === 'charmm_tip3p' ? $('padding-nm').value : 1,temperature_k:$('temperature').value,timestep_fs:$('timestep').value};
}
function showCompatibility(result) {
  const labels = {deferred:'Decide later',compatible:'Compatible in this OpenMM check',needs_input:'More files needed',requires_preparation:'Additional preparation required',failed:'Compatibility check failed',unavailable:'OpenMM unavailable',incomplete:'Readiness test incomplete',not_checked:'Not checked'};
  $('compatibility-status').textContent = `${labels[result.status] || result.status}: ${result.message}` +
    (result.openmm_version ? ` OpenMM ${result.openmm_version}; ${result.particles} particles.` : '') +
    (result.required ? `\n${result.required.join('\n')}` : '') +
    (result.box ? `\n${result.box.water_molecules} TIP3 waters; cubic periodic box ${result.box.box_vectors_nm[0][0].toFixed(3)} nm; PME; 0 added ions; no neutralization.` : '') +
    (result.implicit_salt_note ? `\n${result.settings.salt_molar} M ionic screening. ${result.implicit_salt_note}` : '') +
    (result.readiness ? `\nReadiness test passed: ${result.readiness.dynamics_steps} steps (${result.readiness.duration_ps} ps); finite energy, forces and coordinates. This is not production validation.` : '') +
    (result.box ? `\nNet charge: ${result.net_charge_e.toFixed(4)} e (unchanged).` : '') +
    '\nProtonation is not validated by this check. Simulation readiness still requires review.';
  const downloads = $('environment-downloads'); downloads.replaceChildren();
  if (result.storage) {
    for (const [name,url] of Object.entries(result.storage.download_urls)) {
      const link=document.createElement('a'); link.href=url; link.download=name; link.textContent=`Download ${name}`; downloads.append(link);
    }
    downloads.hidden=false;
  }
}
$('solvent-model').addEventListener('change', () => {
  const model = $('solvent-model').value;
  if (['obc2','gbn2'].includes(previousSolvent)) implicitSalt=$('salt-molar').value;
  const implicit = ['obc2','gbn2'].includes(model);
  $('salt-field').hidden = !implicit;
  $('padding-field').hidden = model !== 'charmm_tip3p';
  $('padding-nm').disabled = model !== 'charmm_tip3p';
  $('water-field').hidden = model !== 'charmm_tip3p';
  $('water-files').disabled = model !== 'charmm_tip3p';
  $('salt-molar').disabled = !implicit;
  $('salt-molar').value = implicit ? implicitSalt : '0';
  $('check-compatibility').textContent = model === 'charmm_tip3p' ? 'Build water box + check OpenMM' : 'Check OpenMM compatibility';
  previousSolvent=model; refreshEnvironmentButtons();
});
async function runEnvironmentCheck(readiness=false) {
  if (!prepared || preparing || checking) return;
  const submittedRevision = revision, pair = prepared, settings = environmentSettings();
  checking = true; refreshEnvironmentButtons();
  $('environment-downloads').hidden=true;
  $('compatibility-status').textContent = readiness ? 'Building the selected environment and running the requested bounded NVT test…' : 'Building/checking the selected environment in OpenMM…';
  try {
    const [topologies,parameters,water] = await Promise.all([readFiles('topologies'),readFiles('parameters'),settings.solvent_model==='charmm_tip3p' ? readFiles('water-files') : []]);
    if (revision !== submittedRevision) return;
    const response = await fetch(readiness ? '/api/runs' : '/api/compatibility', {method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pdb:pair.pdb,psf:pair.psf,topologies,parameters,water,settings})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Compatibility check failed.');
    if (readiness) {
      startRunMonitor(result.id,submittedRevision);
      $('live-monitor').scrollIntoView({behavior:'smooth',block:'start'});
      return;
    }
    if (revision !== submittedRevision) return;
    showCompatibility(result);
  } catch(error) {
    if (revision === submittedRevision) $('compatibility-status').textContent = error.message;
  } finally { checking = false; refreshEnvironmentButtons(); }
}
$('check-compatibility').addEventListener('click',()=>runEnvironmentCheck(false));
$('test-readiness').addEventListener('click',()=>runEnvironmentCheck(true));
function download(name, content, mime='text/plain') {
  const url = URL.createObjectURL(new Blob([content], {type:mime}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function downloadSaved(name) {
  if (!prepared) return;
  const a = document.createElement('a');
  a.href = prepared.storage.download_urls[name]; a.download = name; a.click();
}
$('download-pdb').onclick = () => downloadSaved('prepared.pdb');
$('download-psf').onclick = () => downloadSaved('prepared.psf');
$('download-manifest').onclick = () => downloadSaved('manifest.json');
$('download-bundle').onclick = () => downloadSaved('preparation.zip');
$('pdb').addEventListener('change', async () => {
  invalidate(); pdb = ''; const file = $('pdb').files[0];
  $('filename').textContent = file ? file.name : 'Local PDB · max 5 MB';
});
$('plan-form').addEventListener('submit', async event => {
  event.preventDefault(); $('error').textContent = ''; invalidate();
  const submittedRevision = revision;
  $('propose').disabled = true;
  try {
    if (!prepared) throw Error('Prepare or upload the PSF/PDB pair first.');
    const pair = prepared;
    pdb = pair.pdb;
    const settings = {...environmentSettings(),temperature_k:$('temperature').value,duration_ps:$('duration').value,
      equilibration_ps:$('equilibration').value,timestep_fs:$('timestep').value};
    const [topologies,parameters,water] = await Promise.all([readFiles('topologies'),readFiles('parameters'),settings.solvent_model==='charmm_tip3p' ? readFiles('water-files') : []]);
    if (revision !== submittedRevision) return;
    const response = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pdb, psf:pair.psf, preparation_options:pair.manifest.details.options || {},
        topologies,parameters,water,check_compatibility:true,request:$('request').value,settings})});
    const result = await response.json();
    if (revision !== submittedRevision) return;
    if (!response.ok) throw Error(result.error || 'Could not create a plan.');
    plan = result; yaw = pitch = 0; zoom = 1;
    showCompatibility(result.compatibility);
    $('status').textContent = 'Proposed'; $('export').disabled = false;
    $('structure-info').textContent = `${plan.structure.atom_count} atoms · ${plan.structure.residue_count} residues · ${plan.structure.chains.length} chains`;
    for (const step of plan.steps) {
      const li = document.createElement('li'), text = document.createElement('small');
      li.textContent = step.name; text.textContent = step.action;
      li.append(text); $('steps').append(li);
    }
    $('decisions').replaceChildren(...plan.decisions.map(value => {
      const li = document.createElement('li'); li.textContent = value; return li;
    }));
    $('review').hidden = false; $('events').textContent = plan.events[0].message;
    $('record').textContent = JSON.stringify(plan, null, 2); draw();
  } catch(error) { if (revision === submittedRevision) { $('error').textContent = error.message; $('status').textContent = 'Needs attention'; } }
  finally { $('propose').disabled = !prepared || preparing; }
});
$('detailed').addEventListener('change', () => $('record').hidden = !$('detailed').checked);
$('export').addEventListener('click', () => {
  if (!plan) return;
  // Include the exact source alongside its hash for a self-contained planning record.
  const url = URL.createObjectURL(new Blob([JSON.stringify({...plan, input_pdb:pdb, input_psf:prepared?.psf, preparation_record:prepared?.manifest}, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `molvis-plan-${plan.id}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
function draw() {
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio; canvas.height = rect.height * ratio;
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const atoms = (coordinateStructure || plan?.structure || prepared?.structure)?.atoms.filter(a => a.name === 'CA' && a.record === 'ATOM') || [];
  $('empty').hidden = atoms.length > 0;
  if (!atoms.length) return;
  const center = [0,1,2].map(k => atoms.reduce((sum,a) => sum+a.xyz[k],0)/atoms.length);
  const radius = Math.max(1,...atoms.map(a => Math.hypot(...a.xyz.map((v,k) => v-center[k]))));
  const scale = Math.min(rect.width,rect.height)*.36/radius*zoom;
  const points = atoms.map(a => {
    const [x,y,z] = a.xyz.map((v,k)=>v-center[k]);
    const xx=x*Math.cos(yaw)+z*Math.sin(yaw), zz=-x*Math.sin(yaw)+z*Math.cos(yaw);
    return {x:rect.width/2+xx*scale,y:rect.height/2+(y*Math.cos(pitch)-zz*Math.sin(pitch))*scale,chain:a.chain};
  });
  const chains = (coordinateStructure || plan?.structure || prepared.structure).chains;
  points.forEach((p,i) => {
    ctx.strokeStyle = ctx.fillStyle = colors[chains.indexOf(p.chain)%colors.length];
    ctx.lineWidth=2.5; ctx.lineCap='round';
    if(i && points[i-1].chain===p.chain && Math.hypot(...atoms[i].xyz.map((v,k)=>v-atoms[i-1].xyz[k]))<4.5){
      ctx.beginPath(); ctx.moveTo(points[i-1].x,points[i-1].y); ctx.lineTo(p.x,p.y); ctx.stroke();
    }
    ctx.beginPath();ctx.arc(p.x,p.y,2.4,0,Math.PI*2);ctx.fill();
  });
}
canvas.onpointerdown = e => {dragging=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};
canvas.onpointermove = e => {if(!dragging)return; yaw+=(e.clientX-dragging[0])*.01;pitch+=(e.clientY-dragging[1])*.01;dragging=[e.clientX,e.clientY];draw();};
canvas.onpointerup = canvas.onpointercancel = () => dragging=null;
canvas.addEventListener('wheel', e => {e.preventDefault();zoom=Math.max(.3,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
new ResizeObserver(draw).observe(canvas);

const svgNS = 'http://www.w3.org/2000/svg';
function svgElement(tag, attributes={}, text) {
  const element=document.createElementNS(svgNS,tag);
  for (const [name,value] of Object.entries(attributes)) element.setAttribute(name,String(value));
  if (text !== undefined) element.textContent=text;
  return element;
}
function measuredNumber(value) {
  return Number.isFinite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:3}) : '—';
}
function drawMeasurementChart(id, samples, xField, series, xLabel, yLabel, target=null) {
  const svg=$(id); svg.replaceChildren();
  const left=78,right=540,top=18,bottom=215;
  const valid=samples.filter(s=>Number.isFinite(s[xField]));
  const values=valid.flatMap(s=>series.map(line=>s[line.key]).filter(Number.isFinite));
  if (!values.length) {
    svg.append(svgElement('text',{x:280,y:120,'text-anchor':'middle',fill:'#72817a','font-size':13},'Waiting for real OpenMM measurements'));
    return;
  }
  let xmin=Math.min(...valid.map(s=>s[xField])), xmax=Math.max(...valid.map(s=>s[xField]));
  if (xmin===xmax) xmax=xmin+(xField==='time_ps' ? .02 : 1);
  let ymin=Math.min(...values,...(Number.isFinite(target) ? [target] : []));
  let ymax=Math.max(...values,...(Number.isFinite(target) ? [target] : []));
  const padding=Math.max((ymax-ymin)*.1,Math.abs(ymax)*.005,.01); ymin-=padding;ymax+=padding;
  const x=value=>left+(value-xmin)/(xmax-xmin)*(right-left);
  const y=value=>bottom-(value-ymin)/(ymax-ymin)*(bottom-top);
  for(let i=0;i<=4;i++) {
    const yy=top+(bottom-top)*i/4, xx=left+(right-left)*i/4;
    svg.append(svgElement('line',{x1:left,x2:right,y1:yy,y2:yy,stroke:'#e4eae0'}));
    const tick=ymax-(ymax-ymin)*i/4;
    svg.append(svgElement('text',{x:left-8,y:yy+4,'text-anchor':'end',fill:'#72817a','font-size':10},Math.abs(tick)>=10000 ? tick.toExponential(1) : tick.toFixed(Math.abs(tick)<1 ? 3 : 1)));
    svg.append(svgElement('text',{x:xx,y:bottom+17,'text-anchor':'middle',fill:'#72817a','font-size':10},measuredNumber(xmin+(xmax-xmin)*i/4)));
  }
  svg.append(svgElement('text',{x:(left+right)/2,y:252,'text-anchor':'middle',fill:'#263c36','font-size':11},xLabel));
  svg.append(svgElement('text',{x:14,y:115,transform:'rotate(-90 14 115)','text-anchor':'middle',fill:'#263c36','font-size':11},yLabel));
  if (Number.isFinite(target)) svg.append(svgElement('line',{x1:left,x2:right,y1:y(target),y2:y(target),stroke:'#8d9690','stroke-dasharray':'5 4'}));
  for(const line of series) {
    const points=valid.filter(s=>Number.isFinite(s[line.key]));
    svg.append(svgElement('path',{d:points.map((s,i)=>`${i?'L':'M'}${x(s[xField])},${y(s[line.key])}`).join(' '),fill:'none',stroke:line.color,'stroke-width':2}));
    for (const sample of points) {
      const point=svgElement('circle',{cx:x(sample[xField]),cy:y(sample[line.key]),r:2.5,fill:line.color});
      point.append(svgElement('title',{},`${line.label}: ${measuredNumber(sample[line.key])} ${yLabel}; ${xLabel}: ${measuredNumber(sample[xField])}`));svg.append(point);
    }
  }
}
function renderMeasurements(record) {
  if (record.coordinates && record.coordinates.sequence!==coordinateStructure?.sequence) {
    coordinateStructure=record.coordinates; draw();
    $('structure-info').textContent=`${record.coordinates.atoms.length} Cα atoms · run ${record.id?.slice(0,8) || ''}`;
    $('coordinate-status').textContent=`Run ${record.id?.slice(0,8) || ''} Cα snapshot · step ${record.coordinates.step} · ${measuredNumber(record.coordinates.time_ps)} ps. Latest available coordinates; water is omitted.`;
  }
  const dynamics=record.samples.filter(s=>s.stage==='dynamics');
  const minimum=record.samples.filter(s=>s.stage==='minimization');
  drawMeasurementChart('temperature-plot',dynamics,'time_ps',[{key:'temperature_k',color:'#326ba8',label:'Temperature'}],'Simulation time / ps','K',record.settings.temperature_k);
  drawMeasurementChart('energy-plot',dynamics,'time_ps',[
    {key:'potential_energy_kj_mol',color:'#206b50',label:'Potential'},
    {key:'kinetic_energy_kj_mol',color:'#a86d1b',label:'Kinetic'},
    {key:'total_energy_kj_mol',color:'#8c4f99',label:'Total'}],'Simulation time / ps','kJ/mol');
  drawMeasurementChart('minimization-plot',minimum,'report_index',[{key:'potential_energy_kj_mol',color:'#206b50',label:'System potential'}],'Optimizer report #','kJ/mol');
  for(const channel of ['temperature','energy']) {
    const field=channel==='temperature' ? 'temperature_k' : 'potential_energy_kj_mol';
    const latest=dynamics.filter(s=>Number.isFinite(s[field])).at(-1);
    const row=$('latest-'+channel);
    row.children[1].textContent=latest ? measuredNumber(latest.time_ps) : '—';
    row.children[2].textContent=!latest ? 'Waiting for dynamics.' : channel==='temperature'
      ? `${measuredNumber(latest.temperature_k)} K`
      : `Potential ${measuredNumber(latest.potential_energy_kj_mol)} · kinetic ${measuredNumber(latest.kinetic_energy_kj_mol)} · total ${measuredNumber(latest.total_energy_kj_mol)} kJ/mol`;
  }
}
function updateReadinessLength(timestep=Number($('timestep').value)) {
  const steps=Number($('readiness-steps').value),ps=steps*timestep/1000;
  $('readiness-spacing').textContent=`${steps} steps × ${timestep} fs = ${ps.toLocaleString(undefined,{maximumFractionDigits:6})} ps`;
  $('test-readiness').textContent=`Run + plot NVT (${steps} steps)`;
}
$('readiness-steps').addEventListener('input',()=>{updateReadinessLength();settingsChanged({target:$('readiness-steps')});});
$('timestep').addEventListener('input',()=>updateReadinessLength());
updateReadinessLength();
function updateOutputSpacing(timestep=Number($('timestep').value)) {
  for(const channel of ['coordinates','energy','temperature']) {
    const steps=Number($(channel+'-interval').value),fs=steps*timestep;
    $(channel+'-spacing').textContent=Number.isInteger(steps) && steps>0 ? `${steps} steps × ${timestep} fs = ${measuredNumber(fs)} fs (${(fs/1000).toLocaleString(undefined,{maximumFractionDigits:6})} ps)` : 'Enter a positive whole number of steps.';
  }
}
for(const channel of ['coordinates','energy','temperature']) {
  const control=$(channel+'-interval');
  try {
    const saved=Number(localStorage.getItem('molvis-'+channel+'-interval-steps'));
    if(Number.isInteger(saved) && saved>=1 && saved<=100000) control.value=saved;
  } catch {}
  control.addEventListener('input',()=>{
    updateOutputSpacing(); settingsChanged({target:control});
    if(control.validity.valid) {try {localStorage.setItem('molvis-'+channel+'-interval-steps',control.value);} catch {}}
  });
}
$('timestep').addEventListener('input',()=>updateOutputSpacing());
updateOutputSpacing();

function showRunOutputIntervals(record) {
  const running=['queued','running','cancelling'].includes(record.status);
  $('display-frequency').querySelector('legend').textContent=running ? 'Output intervals · current run' : 'Output intervals · next run';
  if(running) {
    $('readiness-steps').value=record.settings.dynamics_steps ?? 100;
    for(const channel of ['coordinates','energy','temperature']) $(channel+'-interval').value=record.settings[channel+'_interval_steps'] ?? 10;
  }
  updateOutputSpacing(running ? record.settings.timestep_fs : Number($('timestep').value));
  updateReadinessLength(running ? record.settings.timestep_fs : Number($('timestep').value));
}

async function startRunMonitor(identifier, submittedRevision=null) {
  if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(identifier)) return;
  const monitor={id:identifier,revision:submittedRevision};activeRun=monitor;
  coordinateStructure=null;
  draw();
  liveRunning=true;refreshEnvironmentButtons();
  try {localStorage.setItem('molvis-live-run',identifier);} catch {}
  let failures=0;
  while (activeRun===monitor) {
    try {
      const response=await fetch(`/api/runs/${identifier}`);
      if (response.status===404) {
        liveRunning=false;refreshEnvironmentButtons();$('stop-run').disabled=true;
        $('run-status').textContent='Saved run not found. You can prepare a new run.';
        try {localStorage.removeItem('molvis-live-run');} catch {}
        return;
      }
      const record=await response.json();
      if (!response.ok) throw Error(record.error || 'Run not found.');
      if (activeRun!==monitor) return;
      failures=0;
      liveRunning=['queued','running','cancelling'].includes(record.status);
      $('stop-run').disabled=!liveRunning || record.status==='cancelling';
      showRunOutputIntervals(record);
      $('run-status').textContent=`${record.status} · ${record.progress?.stage || 'waiting'} · ${record.samples.length} measured samples${record.progress?.step!==undefined ? ` · ${record.progress.step}/${record.progress.total_steps} steps` : ''}`;
      $('run-description').textContent=`Run ${identifier.slice(0,8)} · ${record.settings.solvent_label} · target ${record.settings.temperature_k} K · timestep ${record.settings.timestep_fs} fs · ${record.settings.dynamics_steps ?? 100} requested steps (${(record.settings.dynamics_steps ?? 100)*record.settings.timestep_fs/1000} ps). Measurements belong to this saved run; changing form settings will not alter it. Outputs: ${record.settings.coordinates_interval_steps ? `coordinates every ${record.settings.coordinates_interval_steps} steps` : 'no coordinate preview recorded'}; energy every ${record.settings.energy_interval_steps ?? 10} steps; temperature every ${record.settings.temperature_interval_steps ?? 10} steps.`;
      renderMeasurements(record);
      const links=$('run-downloads'),key=`${identifier}-${record.status}-${Object.keys(record.artifact_urls || {}).join(',')}`;
      if (links.dataset.runKey!==key) {
        links.dataset.runKey=key;links.replaceChildren();
        const urls={'measurements.jsonl':`/api/runs/${identifier}/measurements.jsonl`,'measurements.csv':`/api/runs/${identifier}/measurements.csv`,...(record.artifact_urls || {}),...(record.result?.storage?.download_urls || {})};
        for(const [name,url] of Object.entries(urls)) {const link=document.createElement('a');link.href=url;link.download=name;link.textContent=`Download ${name}`;links.append(link);}
      }
      refreshEnvironmentButtons();
      if (!liveRunning) {
        if(record.result) {
          $('run-status').textContent+=` · ${record.result.message}`;
          if(monitor.revision!==null && monitor.revision===revision) showCompatibility(record.result);
        }
        return;
      }
    } catch(error) {
      if(activeRun!==monitor) return;
      $('run-status').textContent=`Connection interrupted: ${error.message} Partial data remains saved. Retrying…`;
      if (++failures>=5) {$('run-status').textContent+=' Reload to reconnect; the worker may still be running.';return;}
    }
    await new Promise(resolve=>setTimeout(resolve,failures ? 1000 : 300));
  }
}
$('stop-run').addEventListener('click',async()=>{
  if (!activeRun || !liveRunning) return;
  $('stop-run').disabled=true;
  try {
    const response=await fetch(`/api/runs/${activeRun.id}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if(!response.ok) throw Error('Could not stop run.');
    $('run-status').textContent='Stopping the OpenMM worker; partial measurements will be retained.';
  } catch(error) {$('run-status').textContent=error.message;$('stop-run').disabled=false;}
});
renderMeasurements({samples:[],settings:{temperature_k:300}});
let savedRun=new URLSearchParams(location.search).get('run');
try {savedRun=savedRun || localStorage.getItem('molvis-live-run');} catch {}
if (savedRun) startRunMonitor(savedRun);
