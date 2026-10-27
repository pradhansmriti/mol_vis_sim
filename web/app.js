const $ = id => document.getElementById(id);
let plan = null, pdb = '', yaw = 0, pitch = 0, zoom = 1, dragging = null, revision = 0, prepared = null, preparing = false;
const canvas = $('structure'), ctx = canvas.getContext('2d');
const colors = ['#26785b','#d09843','#5188a3','#9c6d9c'];
function invalidate() {
  revision++;
  plan = null; $('export').disabled = true; $('review').hidden = true;
  $('status').textContent = 'Settings changed'; $('steps').replaceChildren();
  $('events').textContent = 'Propose a workflow to review the current input.';
  $('record').textContent = ''; $('structure-info').textContent = 'No current plan';
  draw();
}
const preparationInputs = new Set(['pdb','psf','topologies','parameters','histidine','first-patch','last-patch','confirm-guess','prep-mode']);
$('plan-form').addEventListener('input', event => {
  if (preparationInputs.has(event.target.id)) {
    prepared = null; $('prep-downloads').hidden = true;
    $('prep-status').textContent = 'Inputs changed. Prepare the files again.';
  }
  invalidate(); $('propose').disabled = !prepared || preparing;
});
$('prep-mode').addEventListener('change', () => {
  const generate = $('prep-mode').value === 'generate';
  $('psf-field').hidden = generate; $('psf').disabled = generate; $('psf').required = !generate;
  $('topology-field').hidden = !generate; $('topologies').disabled = !generate; $('topologies').required = generate;
  $('generation-options').hidden = !generate;
  $('prepare').textContent = generate ? 'Generate PSF + PDB' : 'Check PSF + PDB pair';
  $('prep-help').textContent = generate ? 'Standard proteins only; resolve chain gaps, alternate positions and custom/disulfide patches first. HIS aliases and termini are applied as selected. No minimization or solvation is performed.' : 'Upload files from the same preparation. Atom count and ordered identity must match. Existing coordinates and topology are retained; bonded terms and force-field parameters are not validated.';
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
  const submittedRevision = revision, mode = $('prep-mode').value;
  const options = {histidine:$('histidine').value,first:$('first-patch').value,last:$('last-patch').value};
  const confirm_guess = $('confirm-guess').checked;
  preparing = true; $('prepare').disabled = $('propose').disabled = true;
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
    $('prep-status').textContent = `${result.structure.atom_count} atoms · pair checked. Review coordinates and force-field parameters before simulation.`;
    $('structure-info').textContent = `${result.structure.atom_count} atoms · ${result.structure.residue_count} residues`;
    $('status').textContent = 'Files prepared';
    $('events').textContent = mode === 'generate' ? 'Standalone psfgen produced a matching PSF/PDB pair. No simulation has run.' : 'Uploaded PSF/PDB pair checked. No atoms or coordinates changed.';
    $('record').textContent = JSON.stringify(result.manifest,null,2); draw();
  } catch(error) {
    if (submittedRevision === revision) { $('error').textContent = error.message; $('prep-status').textContent = 'Preparation needs attention.'; }
  } finally { preparing = false; $('prepare').disabled = false; $('propose').disabled = !prepared; }
});
function download(name, content, mime='text/plain') {
  const url = URL.createObjectURL(new Blob([content], {type:mime}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('download-pdb').onclick = () => prepared && download('prepared.pdb',prepared.pdb);
$('download-psf').onclick = () => prepared && download('prepared.psf',prepared.psf);
$('download-bundle').onclick = () => prepared && download('preparation.zip', Uint8Array.from(atob(prepared.bundle_base64), c => c.charCodeAt(0)), 'application/zip');
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
    pdb = prepared.pdb;
    const response = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pdb, psf:prepared.psf, request:$('request').value, settings:{
        temperature_k:$('temperature').value, duration_ps:$('duration').value,
        equilibration_ps:$('equilibration').value, timestep_fs:$('timestep').value}})});
    const result = await response.json();
    if (revision !== submittedRevision) return;
    if (!response.ok) throw Error(result.error || 'Could not create a plan.');
    plan = result; yaw = pitch = 0; zoom = 1;
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
  const atoms = (plan?.structure || prepared?.structure)?.atoms.filter(a => a.name === 'CA' && a.record === 'ATOM') || [];
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
  const chains = (plan?.structure || prepared.structure).chains;
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
