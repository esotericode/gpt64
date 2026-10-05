const $ = id => document.getElementById(id);
let controlToken = '', live = null, archive = '', lastImage = '', busy = false, commandError = '', previousArchive = '';
const terminal = new Set(['idle','error','stopped','completed','limit_reached','budget_reached']);
const phaseNames = {idle:'Ready · emulator paused',observing:'Capturing a screenshot',starting:'Connecting to the emulator',checking_access:'Checking GPT-6.1 SOL access',counting_tokens:'Checking the next request budget',thinking:'Model thinking · game paused',acting:'Executing the input burst',paused:'Paused · next action held',stopping:'Stopping after in-flight work',stopped:'Stopped · emulator paused',completed:'Goal reported complete',limit_reached:'Decision limit reached',budget_reached:'Budget check stopped the run',error:'Run stopped with an error'};
const fmt = n => Number(n || 0).toLocaleString();
function text(id, value) { $(id).textContent = value; }
function render(s) {
  if (archive || previousArchive) { $('goal').value=s.goal || 'Enter Bob-omb Battlefield through its painting.'; $('budget').value=s.budget_usd; $('limit').value=s.max_steps; }
  previousArchive=archive;
  const u = s.usage;
  const plan = s.billing_mode==='chatgpt';
  const auth = live?.auth || {ready:false,accounts:[],label:'Not signed in'};
  text('status',s.status.replaceAll('_',' ').toUpperCase()); text('phase',phaseNames[s.status] || s.status);
  text('commentary',s.commentary); text('decisionlabel',s.decisions ? `Decision ${s.decisions}${s.pending_decision ? ' · pending' : ''}` : 'Public action summary');
  text('cost',plan ? 'ChatGPT plan' : `$${Number(u.estimated_usd).toFixed(4)}`);
  text('costlabel',plan ? 'Using ChatGPT plan or available credits' : s.demo ? 'Demo · no model usage' : 'Estimated API cost');
  text('budgettext',plan ? 'Allowance and app limits are managed in ChatGPT settings' : `$${Number(s.budget_usd).toFixed(2)} budget estimate`);
  $('budgetfield').hidden=$('budgettrack').hidden=plan;
  text('usagehint',plan ? 'Tokens are recorded for this run. Remaining plan allowance and credit charges are shown in ChatGPT settings. No API-price dollar estimate applies.' : 'Token counts come from responses. Dollar estimates use dated standard rates; check OpenAI billing for final charges.');
  $('usagelink').href=plan ? 'https://chatgpt.com/#settings/usage' : 'https://platform.openai.com/usage'; text('usagelink',plan ? 'Manage ChatGPT usage ↗' : 'Open API usage ↗');
  $('budgetbar').style.width = `${Math.min(100,100*u.estimated_usd/s.budget_usd)}%`;
  text('inputtokens',fmt(u.input_tokens)); text('cachetokens',`${fmt(u.cached_tokens)} / ${fmt(u.cache_write_tokens)}`);
  text('outputtokens',fmt(u.output_tokens)); text('reasoningtokens',fmt(u.reasoning_tokens));
  text('steps',`${s.decisions} / ${s.steps}`); text('latency',s.latency_seconds == null ? '—' : `${Number(s.latency_seconds).toFixed(1)} s`);
  text('effort',`${s.reasoning_effort} reasoning`); text('updated',`${archive ? 'Archived run · ' : ''}Updated ${new Date(s.updated).toLocaleTimeString()}`);
  $('reservation').hidden = !s.usage_unknown;
  text('reservation',plan ? 'A request may have consumed plan usage, but its outcome is unconfirmed. Check ChatGPT settings before another run.' : `Unconfirmed usage: up to $${Number(s.reserved_usd).toFixed(4)} reserved at standard rates. Check billing if the request failed.`);
  const ready=plan ? auth.ready : s.key_present;
  $('banner').hidden = !s.demo && (ready || archive);
  text('banner',s.demo ? 'DEMO MODE — synthetic scene and scripted commentary. No Mario emulator or API calls.' : plan ? 'Continue with ChatGPT and grant plan usage. Observe works without signing in.' : 'Paid API mode. Set OPENAI_API_KEY locally before starting the server. Observe works without a key.');
  const errorMessage=s.error || commandError || live?.auth_error;
  $('error').hidden = !errorMessage; text('error',errorMessage || '');
  $('demolabel').hidden = !s.demo; text('viewlabel',archive ? 'Archived screenshot' : 'Latest screenshot');
  if (s.image_url && s.image_url !== lastImage) { $('game').src = s.image_url; lastImage = s.image_url; }
  $('game').hidden = !s.image_url; $('empty').hidden = !!s.image_url;
  $('inputs').replaceChildren();
  text('inputslabel',s.pending_decision ? 'INPUTS SELECTED · PENDING' : 'LATEST SELECTED INPUTS');
  if (!s.segments.length) { const span = document.createElement('span'); span.className='pill muted'; span.textContent='No inputs'; $('inputs').append(span); }
  s.segments.forEach((seg,i) => { const span=document.createElement('span'); span.className='pill'; span.textContent=`${i+1}. ${seg.buttons.join(' + ') || 'neutral'} · (${seg.x}, ${seg.y}) · ${seg.frames}f`; $('inputs').append(span); });
  const stick = s.segments[0] || {x:0,y:0}; $('stickdot').setAttribute('cx',30+stick.x*20); $('stickdot').setAttribute('cy',30-stick.y*20); text('axis',`x ${stick.x} · y ${stick.y}`);
  const active = !terminal.has(s.status); const resumable = s.status==='paused';
  ['goal','budget','limit'].forEach(id => $(id).disabled=active || !!archive);
  const authBusy=live?.auth_status && live.auth_status!=='idle';
  $('start').disabled=!!archive || (active && !resumable) || (!s.demo && !ready) || authBusy; $('start').firstChild.textContent=resumable ? 'Resume run ' : 'Start run ';
  $('step').disabled=$('start').disabled; $('observe').disabled=!!archive || active;
  $('pause').disabled=!!archive || !active || resumable || s.status==='stopping'; $('stop').disabled=!!archive || !active || s.status==='stopping';
  $('accountpanel').hidden=live?.billing_mode!=='chatgpt';
  text('accountlabel',auth.label);text('authstatus',authBusy ? 'OPENAI BROWSER / PLEASE WAIT' : auth.ready ? 'PLAN ENABLED' : 'SIGN IN');
  $('accounts').replaceChildren();
  if(!auth.accounts.length)$('accounts').append(new Option('No saved accounts',''));
  auth.accounts.forEach(a=>$('accounts').append(new Option(a.label,a.id)));$('accounts').value=auth.active || '';
  ['login','addaccount','logout','accounts'].forEach(id=>$(id).disabled=!!archive || !terminal.has(live?.status) || authBusy);
  if(!auth.active)$('logout').disabled=true;
  if(auth.welcome && !archive && !$('welcome').open)$('welcome').showModal();
  $('export').hidden=$('events').hidden=!s.run_id;
  if(s.run_id){$('export').href=`/api/runs/${s.run_id}/export`; $('events').href=`/api/runs/${s.run_id}/events.jsonl`;}
  const visible = s.events.filter(e => ['decision','action_finished','api_request_finished','error','run_started','budget_reached','goal_completed','run_stopped','pause_requested','stop_requested'].includes(e.event)).slice(-40).reverse();
  $('timeline').replaceChildren();
  if(!visible.length){const p=document.createElement('p');p.className='placeholder';p.textContent='Commentary, inputs, usage, and errors will appear here.';$('timeline').append(p);}
  visible.forEach(e=>{const row=document.createElement('div');row.className='entry';const head=document.createElement('div');head.className='entryhead';const title=document.createElement('b');title.textContent=e.event.replaceAll('_',' ');const time=document.createElement('span');time.textContent=new Date(e.time).toLocaleTimeString();head.append(title,time);row.append(head);const p=document.createElement('p');p.textContent=e.commentary || e.message || (e.event==='action_finished' ? `${e.advanced} frames confirmed. Controls released.` : e.event==='api_request_finished' ? `${fmt(e.usage.total_tokens)} tokens · ${e.billing_mode==='chatgpt' ? 'ChatGPT plan' : '$'+e.usage.estimated_usd.toFixed(5)} · ${e.latency_seconds.toFixed(1)} s` : e.goal || '');row.append(p);if(e.segments){const d=document.createElement('p');d.className='detail';d.textContent=e.segments.map(x=>`${x.buttons.join('+') || 'neutral'} (${x.x},${x.y}) ${x.frames}f`).join(' → ');row.append(d);} $('timeline').append(row);});
}
async function refresh(){
  if(busy)return;busy=true;
  try{const r=await fetch('/api/state');if(!r.ok)throw Error('Dashboard unavailable');live=await r.json();controlToken=live.control_token;
    let s=live;if(archive){const old=await fetch(`/api/runs/${archive}/state`);if(!old.ok)throw Error('Saved run unavailable');s=await old.json();}
    render(s);text('connection',archive?'Viewing saved run':'Connected locally');$('dot').classList.remove('off');
  }catch(e){text('connection',e.message);$('dot').classList.add('off');['start','step','observe','pause','stop'].forEach(id=>$(id).disabled=true);}finally{busy=false;}
}
async function command(name,extra={}){
  commandError='';
  $('error').hidden=true;
  try{const r=await fetch(`/api/${name}`,{method:'POST',headers:{'Content-Type':'application/json','X-Gpt64-Control':controlToken},body:JSON.stringify({goal:$('goal').value,max_steps:Number($('limit').value),budget_usd:Number($('budget').value),...extra})});const d=await r.json();if(!r.ok)throw Error(d.error);await refresh();setTimeout(loadRuns,500);
  }catch(e){commandError=e.message;text('error',e.message);$('error').hidden=false;}
}
async function loadRuns(){try{const r=await fetch('/api/runs');const runs=await r.json();$('runs').replaceChildren(new Option('Live dashboard',''));runs.forEach(s=>$('runs').append(new Option(`${s.demo?'Demo · ':''}${s.goal.slice(0,35)} · ${s.steps} actions · ${s.status}`,s.run_id)));$('runs').value=archive;}catch{}}
['start','step','pause','stop','observe'].forEach(name=>$(name).addEventListener('click',()=>command(name)));
$('login').addEventListener('click',()=>command('auth/login',{enable_plan:!live?.auth?.ready}));
$('addaccount').addEventListener('click',()=>command('auth/login',{new:true}));
$('logout').addEventListener('click',()=>command('auth/logout'));
$('accounts').addEventListener('change',()=>command('auth/select',{account:$('accounts').value}));
$('gotit').addEventListener('click',async()=>{await command('auth/ack');$('welcome').close();});
$('welcome').addEventListener('cancel',e=>{e.preventDefault();$('gotit').click();});
$('runs').addEventListener('change',()=>{archive=$('runs').value;lastImage='';refresh();});
refresh();loadRuns();setInterval(refresh,350);setInterval(loadRuns,8000);
