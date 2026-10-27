const $ = id => document.getElementById(id);
let plan = null, pdb = '', yaw = 0, pitch = 0, zoom = 1, dragging = null, revision = 0;
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
$('plan-form').addEventListener('input', invalidate);
$('pdb').addEventListener('change', async () => {
  invalidate(); pdb = ''; const file = $('pdb').files[0];
  $('filename').textContent = file ? file.name : 'Local PDB · max 5 MB';
});
$('plan-form').addEventListener('submit', async event => {
  event.preventDefault(); $('error').textContent = ''; invalidate();
  const submittedRevision = revision;
  $('propose').disabled = true;
  try {
    const file = $('pdb').files[0];
    if (!file || file.size > 5_000_000) throw Error('Choose a PDB file smaller than 5 MB.');
    pdb = await file.text();
    const response = await fetch('/api/plan', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({pdb, request:$('request').value, settings:{
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
  finally { $('propose').disabled = false; }
});
$('detailed').addEventListener('change', () => $('record').hidden = !$('detailed').checked);
$('export').addEventListener('click', () => {
  if (!plan) return;
  // Include the exact source alongside its hash for a self-contained planning record.
  const url = URL.createObjectURL(new Blob([JSON.stringify({...plan, input_pdb:pdb}, null, 2)], {type:'application/json'}));
  const a = document.createElement('a'); a.href = url; a.download = `molvis-plan-${plan.id}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
function draw() {
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = rect.width * ratio; canvas.height = rect.height * ratio;
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const atoms = plan?.structure.atoms.filter(a => a.name === 'CA' && a.record === 'ATOM') || [];
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
  const chains = plan.structure.chains;
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
