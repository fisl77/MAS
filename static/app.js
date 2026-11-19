const $ = (s) => document.querySelector(s);
const escape = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (v, d=0) => Number(v || 0).toLocaleString('en-US', {maximumFractionDigits:d});
const coins = v => number(Number(v || 0)/100, 2);
const colors = ['#33705c','#c28655','#678fa2','#9584a0','#b3a25e'];
const profileLabels = {short_term:'Near-term profit seeker',reciprocal:'Reciprocal strategist',cunning_experimenter:'Cunning experimenter'};
const profileDescriptions = {
  short_term:'Prioritizes near-term profit and liquidity.',
  reciprocal:'Considers repeated interaction and reciprocates reliability.',
  cunning_experimenter:'Curious, cautious and calculating. Uses experiments, deception and advantageous agreements to outlast rivals.'
};
// Runs recorded before configurable capital started with 200 coins.
const startingCoins = s => s.config.starting_coins ?? 200;
let current = localStorage.getItem('water-lab-run') || '', tab='overview', data=null, agent='A', events=[], cursor=0, polling=false;
let experimentsCache = null, experimentResults = null;
const titles = {overview:'The common ground.',agents:'Inside the farm.',conversation:'A space to negotiate.',agreements:'Promises, measured.',experiments:'Compare the conditions.',events:'Every action, accounted for.'};

async function api(path, method='GET', body) {
  const response = await fetch('/api'+path, {method, headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail));
  return value;
}
function notice(message, error=false) { $('#notice').hidden=!message; $('#notice').textContent=message; $('#notice').setAttribute('role',error?'alert':'status'); }
function syncRunError(error) {
  const panel=$('#notice');
  if(error) { notice(error,true); panel.dataset.runError=error; }
  else if(panel.dataset.runError) {
    if(panel.textContent===panel.dataset.runError) notice('');
    delete panel.dataset.runError;
  }
}
function badge(text, cls='') { return `<span class="badge ${cls}">${escape(text)}</span>`; }
function empty(text, icon='◇') { return `<div class="empty-state"><span class="large-icon">${icon}</span>${escape(text)}</div>`; }
function table(headers, rows) { return `<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th>${escape(x)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`; }
function row(cells) { return `<tr>${cells.map(c=>`<td>${c}</td>`).join('')}</tr>`; }
function metric(label,value,unit,note,feature=false) { return `<div class="metric ${feature?'feature':''}"><div class="label">${label}<span>${feature?'◒':'↗'}</span></div><div class="value">${value} <small>${unit}</small></div><div class="note">${note}</div></div>`; }
function chart(history, field='pond', currency=false) {
  if (!history.length) return '<div class="empty-chart">The resource story starts with the first round.</div>';
  const values=history.map(h=>Number(h[field])/(currency?100:1));
  const min=Math.min(0,...values),max=Math.max(1,...values)*1.08,w=640,h=205,left=48,top=12,bottom=28;
  const x=i=>left+(w-left-8)*(history.length===1?0:i/(history.length-1));
  const y=v=>top+(h-top-bottom)*(1-(v-min)/(max-min));
  const path=values.map((v,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const grid=[0,1,2,3].map(i=>{const v=min+(max-min)*i/3;return `<line class="grid" x1="${left}" x2="${w}" y1="${y(v)}" y2="${y(v)}"/><text x="${left-9}" y="${y(v)+4}" text-anchor="end">${number(v)}</text>`;}).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${currency?'Social profit':'Pond volume'} over ${history.length} rounds">${grid}<path d="${path} L${x(values.length-1)},${y(min)} L${x(0)},${y(min)} Z" fill="#dce9df" opacity=".7"/><path d="${path}" fill="none" stroke="#33705c" stroke-width="2.5" stroke-linecap="round"/><circle cx="${x(values.length-1)}" cy="${y(values.at(-1))}" r="4" fill="#33705c"/><text x="${left}" y="${h-4}">Round ${history[0].round}</text><text x="${w}" y="${h-4}" text-anchor="end">${history.at(-1).round}</text></svg>`;
}
function meta(s) { return `<div class="meta-line">${badge(s.config.test_mode?'TECHNICAL TEST':'REGULAR RESEARCH',s.config.test_mode?'test':'')}<span>${s.config.controller==='test'?'Scripted agents · Not LLM results':escape(s.config.model)}</span><span>·</span><span>${s.config.agent_count} farms</span><span>·</span><span>Communication ${s.config.communication?'on':'off'}</span><span>·</span><span>Weather seed ${s.config.seed}</span><span>·</span><span>${number(startingCoins(s))} starting coins / farm</span></div>`; }
function weather(s) { return `<div class="weather-strip">${s.news.forecast.map(d=>`<div class="weather-day ${d.weather==='rain'?'rain':''}"><span class="weather-date">R${d.round}</span><span class="weather-icon">${d.weather==='rain'?'☂':'☀'}</span>${d.weather==='rain'?'Rain':'Dry'}</div>`).join('')}</div>`; }
function farms(s) { return Object.entries(s.agents).map(([id,a],i)=>`<article class="farm-card" style="--farm-color:${colors[i]}"><div class="farm-title"><span class="avatar">${id}</span><div><h3>Farm ${id}</h3><small>${escape(profileLabels[a.profile]||a.profile)}</small></div>${badge(a.active?'ACTIVE':'ELIMINATED',a.active?'':'breached')}</div><div class="farm-stats"><div><strong>${coins(a.bank)}</strong><small>Bank · coins</small></div><div><strong>${coins(a.profit)}</strong><small>Net profit · coins</small></div><div><strong>${number(a.plants.reduce((n,g)=>n+g.count,0))}</strong><small>Living plants</small></div></div><div class="water-bar"><div class="bar-label"><span>Delivered / requested</span><span>${number(a.delivered)} / ${number(a.request)} L</span></div><div class="bar"><div style="width:${a.request?100*a.delivered/a.request:0}%"></div></div></div><div class="farm-bottom"><span>${number(a.used,3)} L used · ${number(a.returned,3)} L returned</span><button class="text-button" data-agent="${id}">Inspect farm ↗</button></div></article>`).join(''); }
function newsPanel(s) { const n=s.news;return `<ul class="news-list"><li><strong>Official NEWS · ${n.round?`Round ${n.round}`:'Before round 1'}</strong></li>${n.net_withdrawals?Object.entries(n.net_withdrawals).map(([id,v])=>`<li>Farm ${id} withdrew <strong>${number(v,3)} L net</strong></li>`).join(''):'<li>Initial common pond: 5,000 liters</li>'}${n.total_plants_sold!==undefined?`<li>${number(n.total_plants_sold)} plants sold across all farms</li>`:''}${n.bank_ranking?`<li>Anonymous balances: ${n.bank_ranking.map(coins).join(' · ')} coins</li>`:''}${n.announcements.map(x=>`<li>${escape(x)}</li>`).join('')}</ul>`; }
function downloads() { return `<div class="toolbar"><a class="download" href="/api/runs/${current}/download/json">↓ Complete JSON</a><a class="download" href="/api/runs/${current}/download/csv">↓ Round data CSV</a><button class="text-button" id="save-export">Save to export directory</button></div>`; }
function overview() {
  if(!data) return `<div class="welcome"><span class="eyebrow">WELCOME TO COMMON WATER LAB</span><h2>What happens when everyone shares the pond?</h2><p>Observe autonomous farms, follow their decisions, and study whether communication changes the way they share a finite resource. Start with a technical pilot to explore the mechanics.</p><button class="primary" id="welcome-create">Set up your first game →</button><div class="steps"><span>01 &nbsp; Define the conditions</span><span>02 &nbsp; Observe the decisions</span><span>03 &nbsp; Compare the outcomes</span></div></div><div class="metric-grid">${metric('Starting resource','5,000','liters','One shared pond',true)}${metric('Starting capital','500','coins','Default per farm · configurable')}${metric('Population','2–5','farms','Individual goals, shared consequences')}${metric('Research horizon','1,000','rounds','Hidden from the playing agents')}</div><div class="panel" style="margin-top:20px"><h3>A researcher’s view, not an agent’s view.</h3><p class="subtle">You can inspect the complete game here. Agents receive only their own farm data, public NEWS, and permitted conversations. Hidden rules stay outside their prompts.</p></div>`;
  const {state:s,metrics:m,execution:e}=data;
  return `${meta(s)}<div class="metric-grid">${metric('Shared pond',number(s.pond,1),'liters',`${number(s.pond/500,1)}% of 50,000 L capacity`,true)}${metric('Social profit',coins(m.social_profit),'coins','Includes eliminated farms')}${metric('Active farms',`${m.active_agents} / ${s.config.agent_count}`,'farms','Survival through the current phase')}${metric('Model activity',number(e.calls),'calls',`${number(e.seconds,1)} s · ${number(e.tokens)} tokens`)}</div><div class="overview-grid"><section class="panel"><div class="panel-head"><div><h3>The shared resource</h3><p>Actual pond volume · researcher only</p></div><span class="legend">Water available</span></div>${chart(s.history)}<div class="chart-caption"><span>Minimum: ${number(m.minimum_pond,1)} L</span><span>Exact fractions retained in exports</span></div></section><section class="panel"><div class="panel-head"><div><h3>Seven days ahead</h3><p>The same forecast every farm receives</p></div><span>☁</span></div>${weather(s)}<p class="rule-note">Rain enters the pond after returns and settlement. Only this seven-day window is visible to agents.</p></section></div><div class="section-heading"><h2>Independent farms</h2><span class="subtle">A closer look at the individual outcomes</span></div><div class="farm-grid">${farms(s)}</div><section class="panel" style="margin-top:20px"><div class="panel-head"><div><h3>The economic outcome</h3><p>Cumulative social profit · includes eliminated farms</p></div><span class="legend">Coins earned, net of fees</span></div>${chart(s.history,"social_profit",true)}</section><div class="summary-grid"><section class="panel"><div class="panel-head"><h3>The public record</h3><span class="subtle">Official NEWS</span></div>${newsPanel(s)}</section><section class="panel"><div class="panel-head"><h3>Cooperation, measured</h3><span class="subtle">Formal agreements</span></div>${table(['Measure','Result'],[row(['Accepted agreements',m.accepted_agreements]),row(['Group compliance',m.agreement_rates.group.rate===null?'Not applicable':`${number(m.agreement_rates.group.rate*100,1)}%`]),row(['Self-commitment compliance',m.agreement_rates.self.rate===null?'Not applicable':`${number(m.agreement_rates.self.rate*100,1)}%`]),row(['Rounds without agreement',m.rounds_without_agreement])])}<p class="subtle" style="margin:15px 0 0">No agreement is neither cooperation nor a breach.</p></section></div>${s.status==='completed'?`<div class="section-heading"><h2>Final ranking</h2></div><section class="panel">${table(['Farm','Profit · coins','Status','Result'],s.ranking.map(x=>row([`Farm ${x.agent_id}`,coins(x.score),x.active?'Active':'Eliminated',x.winner?badge('WINNER'):'—'])))}${s.ranking.some(x=>x.winner)?'': '<p class="subtle">No winner: every farm was eliminated.</p>'}</section>`:''}<div class="section-heading"><h2>Research exports</h2></div>${downloads()}`;
}
function workingMemoryPanel(farm, version) {
  const {memory, profile, last_deliberate_bluff: bluff} = farm;
  if (typeof memory === 'string') {
    return `<pre class="memory">${escape(memory || 'No private notes yet.')}</pre>`;
  }
  const profileLabels = {short_term: 'Cash decision', reciprocal: 'Partner or verification plan',
    cunning_experimenter: 'Experiment or disclosure plan'};
  const labels = {goal: ['farm-agent-1.21','farm-agent-1.22'].includes(version) ? profileLabels[profile] : 'Goal',
    open_question: 'Open question', insight: 'Insight'};
  const notes = Object.entries(labels).filter(([key]) => memory?.[key]);
  let workingNotes = notes.length
    ? table(['Note', 'Content'], notes.map(([key, label]) => row([label, escape(memory[key])])))
    : empty('No private notes yet.');
  if (version === 'farm-agent-1.22') workingNotes += '<button id="note-history">View private note history</button>';
  if (!bluff) return workingNotes;
  return workingNotes + `<h3>Last self-declared bluff</h3><p>Round ${escape(bluff.round)} · phase ${escape(bluff.phase)} · turn ${escape(bluff.turn + 1)}</p>` +
    table(['Public statement', 'Private intended benefit'], [row([escape(bluff.statement), escape(bluff.intended_benefit)])]);
}
async function loadNoteHistory(firstPage) {
  const dialog = $('#note-journal'), more = $('#more-notes'), content = $('#note-changes');
  if (firstPage) {
    dialog.dataset.run = current;
    dialog.dataset.agent = agent;
    $('#note-journal-title').textContent = 'Farm ' + agent + ' · Private note history';
    content.textContent = 'Loading…';
    more.hidden = true;
    dialog.showModal();
  }
  const {run, agent: owner} = dialog.dataset;
  more.disabled = true;
  try {
    const page = await api(`/runs/${run}/agents/${owner}/notes` + (firstPage ? '' : '?before=' + more.dataset.before));
    if (!dialog.open || dialog.dataset.run !== run || dialog.dataset.agent !== owner) return;
    if (firstPage) content.textContent = '';
    const labels = {goal:'Plan', open_question:'Open question', insight:'Insight'};
    const html = page.changes.map(c => {
      const source = c.evidence ? `<details><summary>Evidence · ${escape(c.evidence.ref)}</summary><pre class="memory">${escape(JSON.stringify(c.evidence.record,null,2))}</pre></details>` : '';
      return `<article><p><strong>Round ${escape(c.round)} · phase ${escape(c.phase)} · turn ${escape(c.turn+1)} · ${labels[c.field]}</strong></p><p>${escape(c.value || 'Closed / cleared')}</p>${source}</article>`;
    }).join('');
    content.insertAdjacentHTML('beforeend', html || empty('No changes recorded.'));
    more.dataset.before = page.before || '';
    more.hidden = !page.before;
  } finally {
    more.disabled = false;
  }
}
function evidencePanel(a) {
  const trials=[...(a.cultivation_trials||[])].sort((x,y)=>y.last_round-x.last_round).slice(0,8);
  return `<section class="panel" style="margin-top:20px"><h3>Measured farming experience</h3><p class="subtle">Each row sums this farm’s observations at one dose across rounds. A new plant counts once at sowing. An existing plant counts each round it receives that dose, including zero.</p>${trials.length?table(['Treatment','Water / plant','Plant observations','First / last round','Died','Growth gain','Health after'],trials.map(t=>row([t.kind==='new_plants'?'New plants':'Existing plants',number(t.water_per_plant,3)+' L',number(t.plants_observed),`${t.first_round} / ${t.last_round}`,number(t.plants_died),`${t.growth_gain_min}–${t.growth_gain_max}`,`${t.health_after_min}–${t.health_after_max}`]))):empty('No executed planting experiment has been observed yet.')}</section>`;
}
function agentsView() {
  if(!data)return empty('Create a game to inspect agent observations.');
  const s=data.state,a=s.agents[agent]||Object.values(s.agents)[0]; agent=a.id;
  return `${meta(s)}<div class="toolbar">${Object.keys(s.agents).map(id=>`<button data-select-agent="${id}" class="${id===agent?'primary':''}">Farm ${id}</button>`).join('')}</div><div class="two-col"><section class="panel"><h3>Farm ${agent} · Plant inventory</h3><p class="subtle">Each row groups individual plants with identical states. Last water is per plant, not per group. Groups can be split to water plants differently each round.</p>${a.plants.length?table(['Group','Plants','Growth','Health','Last water / plant'],a.plants.map(g=>row([escape(g.id),number(g.count),`${g.growth}%`,`${g.health} / 20`,`${number(g.water,3)} L`]))):empty('No living plants on this farm.','♧')}</section><section class="panel"><h3>Private working memory</h3>${workingMemoryPanel(a, s.prompt_version)}<h3>Account reconciliation</h3>${table(['Account','Coins'],[row(['Available balance',coins(a.bank)]),row(['Outstanding debt',coins(a.debt)]),row(['Economic net balance',coins(a.bank-a.debt)]),row(['Starting capital + profit',coins(startingCoins(s)*100+a.profit)])])}</section></div>${evidencePanel(a)}<section class="panel" style="margin-top:20px"><h3>Recent plant outcomes</h3>${a.recent_plant_results.length?table(['Round','Group','Water / plant','Growth','Health','Outcome'],a.recent_plant_results.map(x=>row([x.round,escape(x.group.id),number(x.group.water,3)+' L',`${x.before.growth} → ${x.group.growth}`,`${x.before.health} → ${x.group.health}`,escape(x.outcome)]))):empty('Plant outcomes appear after development.')}</section><section class="panel" style="margin-top:20px"><h3>The agent’s actual information boundary</h3><p class="subtle">This filtered observation excludes the pond level, hidden rules, seed, end round, and other farms’ private states.</p><button id="load-observation">Inspect allowed observation</button><pre id="observation-json" hidden></pre></section>`;
}
function conversationEndNote(s) {
  const ended=s.last_conversation_end;if(!ended)return '';
  const reasons={two_quiet_passes:'all farms were silent for two consecutive passes',message_limit:'all active farms used their ten contributions',no_active_agents:'no active farms remain',all_passed:'all eligible farms passed consecutively',repetition:'two full cycles added no new content or agreement change',pass_limit:'the maximum number of passes was reached'};
  return `<p class="rule-note">Last conversation: round ${ended.round}, ${ended.phase===2?'discussion':'after NEWS'} · ended after ${ended.turns !== undefined ? number(ended.turns)+' turns' : number(ended.passes)+' passes'} because ${escape(reasons[ended.reason]||ended.reason)}.</p>`;
}
function conversationBudgetNote(s) {
  const status=data?.conversation;
  if(status) {
    if(!status.phase_open)return '';
    const order=status.eligible_agents.map(id=>'Farm '+escape(id)+' ('+number(status.messages_remaining[id])+' left)');
    return `<p class="rule-note">Next speaker: ${status.next_speaker?'Farm '+escape(status.next_speaker):'none'} · Eligible in order: ${order.join(' → ')||'none'}</p>`;
  }
  const b=s.conversation_budget;if(!b||!s.config.communication)return '';
  return `<p class="rule-note">R${b.round} · ${b.phase===2?'Discussion':'After NEWS'} · Remaining contributions: ${Object.keys(s.agents).map(id=>`Farm ${id}: ${Math.max(0,10-(b.messages_used[id]||0))} / 10`).join(' · ')}. Consecutive silent passes: ${b.quiet_passes} / 2. Skips cost no messages.</p>`;
}
function conversationView() {
  if(!data)return empty('Create a game to inspect conversations.');
  const s=data.state;
  return `${meta(s)}<div class="two-col"><section class="panel"><h3>Official NEWS</h3>${newsPanel(s)}${weather(s)}</section><section class="panel"><h3>Voluntary conversation</h3><p class="subtle">Discussion and post-NEWS only · up to 10 contributions per agent per phase. Peer claims are not verified game facts. Passing is free and does not consume a contribution. ${data.conversation?'Farms speak in order. The phase ends when all eligible farms pass consecutively, two full cycles add nothing new, or everyone uses their budget.':'These recorded messages were published in simultaneous passes.'}</p>${conversationEndNote(s)}${conversationBudgetNote(s)}${!s.config.communication?empty('Communication is off. Optional reflection stays private.'):!s.messages.length?empty('No public contributions yet. Silence is a valid choice.'):[...s.messages].reverse().map(x=>`<article class="message"><div class="message-head"><strong>Farm ${escape(x.sender)}</strong><span>R${x.round} · ${x.phase===2?'Discussion':'After NEWS'} · ${data.conversation?'Turn':'Pass'} ${x.turn+1}</span></div><p>${escape(x.text||(x.contracts.length?'Contract action — no accompanying message.':'No public message or contract action submitted.'))}</p>${x.contracts.length?`<details><summary>${x.contracts.length} contract action(s)</summary><pre>${escape(JSON.stringify(x.contract_results||x.contracts,null,2))}</pre></details>`:''}</article>`).join('')}</section></div>`;
}
function agreementsView() {
  if(!data)return empty('Create a game to inspect agreements.');
  const s=data.state;
  return `${meta(s)}<section class="panel"><h3>Voluntary agreements</h3><p class="subtle">Agreements are voluntary, even after signing. Breaches are recorded without blocking actions or adding fines. Cancellation begins next round; other participants retain their recorded commitments.</p>${s.contracts.length?[...s.contracts].reverse().map(c=>`<article class="contract"><div class="contract-head"><strong>${escape(c.id)} · Version ${c.version} · ${c.participants.length===1?'Self-commitment':'Group agreement'}</strong>${badge(c.status.toUpperCase())}</div><p>Rounds ${c.start_round}–${c.effective_end} · Farms ${c.participants.join(', ')}<br>${c.limits.map(l=>`Farm ${escape(l.agent_id)}: ${l.max_request!==null?`request ≤ ${number(l.max_request)} L`:''}${l.max_request!==null&&l.max_net!==null?' · ':''}${l.max_net!==null?`net withdrawal ≤ ${escape(l.max_net)} L`:''}`).join('<br>')}</p><small>Signatures: ${c.signatures.join(', ')}${Object.keys(c.cancelled_from).length?' · Cancelled from: '+escape(JSON.stringify(c.cancelled_from)):''}${c.replaces?' · Replaces '+escape(c.replaces):''}</small></article>`).join(''):empty('No formal agreements have been proposed.')}</section><section class="panel" style="margin-top:20px"><h3>Agreement evaluations</h3>${s.contract_results.length?table(['Round','Agreement','Kind','Individual results','Joint result'],[...s.contract_results].reverse().map(x=>row([x.round,escape(x.contract_id),x.type,Object.entries(x.individual).map(([id,v])=>`${id}: ${escape(v.status)}`).join('<br>'),badge(x.joint,x.joint==='breached'?'breached':'')]))):empty('Evaluations appear after settlement. No agreement means “not applicable”.')}</section>`;
}
function experimentsView() {
  const es=experimentsCache||[];
  return `<section class="panel"><span class="eyebrow">PAIRED CONDITIONS</span><h2 style="margin-top:12px">Same weather. A different conversation.</h2><p class="subtle">Build a queue from the selected game’s configuration. Each seed and starting position produces a communication-off / communication-on pair with fresh memories. Test games remain clearly labeled.</p><form id="experiment-form" class="experiment-form"><label>Weather seeds<input name="seeds" value="42, 43" required></label><label>Models (Ollama games)<input name="models" value="llama3.2:3b, llama3.1:8b" required></label><label>Starting positions<select name="positions"><option value="all">Balance all farms</option><option value="one">Use selected starting farm</option></select></label><button class="primary" ${data?'':'disabled'}>Create paired queue</button></form><p class="subtle" style="margin:15px 0 0">${data?`Base: ${escape(current)} · ${data.state.config.rounds} rounds · ${data.state.config.controller==='test'?'Scripted technical tests':'Ollama agents'}`:'Select or create a base game first.'}</p></section><div class="section-heading"><h2>Experiment queues</h2><button id="refresh-experiments">Refresh</button></div><section class="panel">${es.length?table(['Experiment','Games','Status','Actions'],es.map(e=>row([escape(e.id),e.runs.length,badge(e.status.toUpperCase()),`<button data-batch-start="${e.id}" ${e.status==='running'||e.status==='completed'?'disabled':''}>Run / resume</button> <button data-batch-pause="${e.id}" ${e.status==='running'?'':'disabled'}>Pause queue</button> <button data-batch-results="${e.id}">Compare</button>`]))):empty('No experiment queues yet.')}<p class="subtle" style="margin-top:18px">The worker runs one game at a time. A technical failure pauses the queue. Use Pause to stop at a safe checkpoint.</p></section>${experimentResults?`<section class="panel" style="margin-top:20px"><h3>Paired results · ${escape(experimentResults.experiment.id)}</h3>${table(['Pair / game','Model','Seed / start','Communication','Status','Social profit','Final pond','Survivors'],experimentResults.results.map(x=>row([`${escape(x.pair)}<br><a class="result-link" data-run="${x.run_id}">${escape(x.run_id)}</a>`,escape(x.config.controller==='test'?'Scripted test':x.config.model),`${x.config.seed} / ${String.fromCharCode(65+x.config.start_agent)}`,x.config.communication?'On':'Off',badge(x.status),coins(x.metrics.social_profit),number(x.metrics.end_pond,1)+' L',x.metrics.active_agents])))}<p class="subtle" style="margin-top:15px">Compare completed pairs only. Equal weather seeds do not guarantee identical model decisions. Agreement compliance is not a cross-condition cooperation score.</p></section>`:''}`;
}
function eventsView() {
  if(!data)return empty('Create a game to inspect its event ledger.');
  return `${meta(data.state)}${downloads()}<section class="panel"><h3>Authoritative event ledger</h3><p class="subtle">Latest ${events.length} loaded events. Complete history and model requests are retained in the JSON export.</p>${events.length?table(['Event','Round / phase','Kind','Details'],[...events].reverse().map(e=>row([e.id,`${e.round} / ${e.phase}`,escape(e.kind),`<details><summary>Inspect event</summary><pre>${escape(JSON.stringify(e,null,2))}</pre></details>`]))):empty('No actions have been executed.')}</section><section class="panel" style="margin-top:20px"><h3>Model trace</h3><p class="subtle">Research-only prompts, raw responses, errors, correction attempts and token counts.</p><button id="load-calls">Load recent model calls</button><pre id="calls-json" hidden></pre></section>`;
}
function render() {
  const scroll=window.scrollY;
  $('#page-title').textContent=titles[tab];
  $('#content').innerHTML=({overview,agents:agentsView,conversation:conversationView,agreements:agreementsView,experiments:experimentsView,events:eventsView}[tab])();
  if(data) {
    const s=data.state;
    const selected=$('#run-select').selectedOptions[0];
    if(selected?.value===current)selected.textContent=`${current} · ${s.config.test_mode?'Test':'Research'} · ${s.status.replaceAll('_',' ')}`;
    $('#run-status').textContent=s.status.replaceAll('_',' ').toUpperCase(); $('#run-status').className='status '+s.status;
    $('#run-position').textContent=`Round ${s.round} / ${s.config.rounds} · ${data.phase_name}${data.progress?' · Farm '+data.progress.agent:''}`;
    $('#start').disabled=s.status==='running'||s.status==='completed'; $('#step').disabled=$('#start').disabled;
    $('#pause').disabled=s.status!=='running'; $('#start').textContent=s.status==='technical_error'||s.status==='interrupted'?'↻ Resume':'▶ Start';
    syncRunError(s.error);
  }
  window.scrollTo(0,scroll);
}
async function refreshRuns() {
  const runs=await api('/runs');
  $('#run-select').innerHTML=runs.length?runs.map(r=>`<option value="${r.id}">${r.id} · ${r.config.test_mode?'Test':'Research'} · ${r.status.replaceAll('_',' ')}</option>`).join(''):'<option value="">Create your first game</option>';
  if(!runs.some(r=>r.id===current))current=runs[0]?.id||'';
  $('#run-select').value=current;
}
async function selectRun(id) {
  current=id; localStorage.setItem('water-lab-run',id);events=[];cursor=0;notice('');
  await refreshRuns(); await refresh(true);
}
async function refresh(force=false) {
  if(polling)return; polling=true;
  try {
    if(current) {
      const id=current, result=await api('/runs/'+id);
      if(id!==current)return;
      const changed=force||!data||JSON.stringify([result.state.round,result.state.phase,result.state.turn,result.state.status,result.execution.calls])!==JSON.stringify([data.state.round,data.state.phase,data.state.turn,data.state.status,data.execution.calls]);
      data=result;
      const fresh=await api(`/runs/${id}/events?after=${cursor}`);
      if(id!==current)return;
      if(fresh.length){cursor=fresh.at(-1).id;events=[...events,...fresh].slice(-300);}
      if(changed||tab==='events'&&fresh.length)render();
    } else if(force)render();
    if(tab==='experiments') {
      const fresh=await api('/experiments');
      if(JSON.stringify(fresh)!==JSON.stringify(experimentsCache)) {
        experimentsCache=fresh;
        if(!document.activeElement?.closest('form'))render();
      }
    }
  } catch(e){notice(e.message,true);} finally {polling=false;}
}
function setupProfiles() {
  const count=Number($('#setup-form').elements.agent_count.value);
  $('#profiles').innerHTML=Array.from({length:count},(_,i)=>{
    const profile=(count===2?i===1:i>=Math.ceil(count/2))?'reciprocal':'short_term';
    return `<label>Farm ${String.fromCharCode(65+i)} profile<select name="profile-${i}" aria-describedby="profile-note-${i}">${Object.entries(profileLabels).map(([value,label])=>`<option value="${value}" ${value===profile?'selected':''}>${label}</option>`).join('')}</select><small id="profile-note-${i}" class="subtle">${profileDescriptions[profile]}</small></label>`;
  }).join('');
  $('#setup-form').elements.start_agent.innerHTML=Array.from({length:count},(_,i)=>`<option value="${i}">Farm ${String.fromCharCode(65+i)}</option>`).join('');
}
async function loadModels(){const chosen=$('#model-select').value;const v=await api('/models');$('#model-status').textContent=v.error||`${v.models.length} installed model(s). No downloads are automatic.`;if(v.models.length){$('#model-select').innerHTML=v.models.map(m=>`<option value="${escape(m.name)}">${escape(m.name)}</option>`).join('');$('#model-select').value=v.models.some(m=>m.name===chosen)?chosen:(v.models.some(m=>m.name==='llama3.1:8b')?'llama3.1:8b':v.models[0].name);}}
function setupVisibility(){const form=$('#setup-form'),llm=form.elements.controller.value==='ollama';$('#model-fields').hidden=!llm;$('#scenario-field').hidden=llm;if(form.elements.test_mode.value==='false'){form.elements.rounds.value=1000;form.elements.rounds.disabled=true;}else form.elements.rounds.disabled=false;}
function showSetup(){ $('#setup-error').textContent='';$('#setup').showModal(); }
$('#new-game').onclick=showSetup; $('#close-setup').onclick=()=>$('#setup').close();
$('#refresh-models').onclick=()=>loadModels().catch(e=>notice(e.message,true));
$('#setup-form').elements.agent_count.onchange=setupProfiles;
$('#profiles').onchange=event=>{
  const select=event.target.closest('select');if(!select)return;
  document.getElementById(select.getAttribute('aria-describedby')).textContent=profileDescriptions[select.value];
};
$('#setup-form').elements.controller.onchange=()=>{setupVisibility();loadModels().catch(e=>notice(e.message,true));};
$('#setup-form').elements.test_mode.onchange=setupVisibility;
$('#setup-form').onsubmit=async event=>{
  event.preventDefault();const form=event.currentTarget, values=Object.fromEntries(new FormData(form));
  const config={...values,agent_count:Number(values.agent_count),profiles:Array.from({length:Number(values.agent_count)},(_,i)=>values[`profile-${i}`]),
    communication:values.communication==='true',test_mode:values.test_mode==='true',rounds:Number(form.elements.rounds.value),
    seed:Number(values.seed),starting_coins:Number(values.starting_coins),start_agent:Number(values.start_agent),temperature:Number(values.temperature),context_tokens:Number(values.context_tokens),output_tokens:Number(values.output_tokens),timeout_seconds:Number(values.timeout_seconds)};
  for(const key of Object.keys(config))if(key.startsWith('profile-'))delete config[key];
  try{const result=await api('/runs','POST',config);$('#setup').close();await selectRun(result.id);}catch(e){$('#setup-error').textContent=e.message;}
};
$('#run-select').onchange=async e=>{data=null;await selectRun(e.target.value);};
for(const command of ['start','step','pause'])$('#'+command).onclick=async()=>{try{notice('');await api(`/runs/${current}/${command}`,'POST');if(command==='pause')notice('Pause requested. The current model call will finish and its decision will be saved.');await refresh(true);}catch(e){notice(e.message,true);}};
document.addEventListener('click',async event=>{
  const button=event.target.closest('button,a');if(!button)return;
  try{
    if(button.dataset.tab){tab=button.dataset.tab;document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));if(tab==='experiments')experimentsCache=await api('/experiments');render();}
    if(button.dataset.agent||button.dataset.selectAgent){agent=button.dataset.agent||button.dataset.selectAgent;tab='agents';document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));render();}
    if(button.id==='welcome-create')showSetup();
    if(button.id==='note-history')await loadNoteHistory(true);
    if(button.id==='more-notes')await loadNoteHistory(false);
    if(button.id==='load-observation'){const o=await api(`/runs/${current}/agents/${agent}`);$('#observation-json').hidden=false;$('#observation-json').textContent=JSON.stringify(o,null,2);}
    if(button.id==='load-calls'){const calls=await api(`/runs/${current}/calls`);$('#calls-json').hidden=false;$('#calls-json').textContent=JSON.stringify(calls.slice(-10),null,2);}
    if(button.id==='save-export'){const r=await api(`/runs/${current}/export`,'POST');notice('Saved JSON and CSV to '+r.directory);}
    if(button.id==='refresh-experiments'){experimentsCache=await api('/experiments');render();}
    if(button.dataset.batchStart){await api(`/experiments/${button.dataset.batchStart}/start`,'POST');experimentsCache=await api('/experiments');render();notice('Experiment queue started. Games run sequentially.');}
    if(button.dataset.batchPause){await api(`/experiments/${button.dataset.batchPause}/pause`,'POST');notice('Queue pause requested. The current decision will be saved before stopping.');}
    if(button.dataset.batchResults){experimentResults=await api(`/experiments/${button.dataset.batchResults}/results`);render();}
    if(button.dataset.run){data=null;await selectRun(button.dataset.run);tab='overview';document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));render();}
  }catch(e){notice(e.message,true);}
});
document.addEventListener('submit',async event=>{
  if(event.target.id!=='experiment-form')return;event.preventDefault();
  try{const v=Object.fromEntries(new FormData(event.target)),seeds=v.seeds.split(',').map(x=>Number(x.trim()));if(seeds.some(x=>!Number.isInteger(x)))throw new Error('Seeds must be comma-separated integers.');await api('/experiments','POST',{base:data.state.config,seeds,models:v.models.split(',').map(x=>x.trim()).filter(Boolean),balance_positions:v.positions==='all'});experimentsCache=await api('/experiments');await refreshRuns();render();notice('Paired queue created. Use Run / resume to execute it.');}catch(e){notice(e.message,true);}
});
setupProfiles();setupVisibility();render();
await refreshRuns();await refresh(true);
setInterval(()=>{if(!$('#setup').open)refresh();},1000);
