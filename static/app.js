let matches=[],rounds=[],selectedRound=null;const $=id=>document.getElementById(id);const pct=v=>v==null?'—':Number(v).toFixed(1)+'%';
async function api(url,opt){const r=await fetch(url,opt);const j=await r.json();if(!j.ok)throw Error(j.error||'Errore');return j}
function tabs(){document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));b.classList.add('active');$(b.dataset.tab).classList.add('active')})}
async function load(){
  const [statusRes,matchesRes,roundsRes,teamsRes]=await Promise.all([
    api('/api/status'),api('/api/matches'),api('/api/rounds'),api('/api/teams')
  ]);
  const s=statusRes.data;
  $('upcoming').textContent=s.upcoming;$('played').textContent=s.played;$('schedule').textContent=s.schedule+'/380';$('updated').textContent=s.updated||'—';
  matches=matchesRes.matches||[];rounds=roundsRes.rounds||[];
  $('teamSelect').innerHTML='<option value="">Seleziona squadra</option>'+((teamsRes.teams)||[]).map(t=>'<option>'+t+'</option>').join('');
  buildRounds();
  const first=+(rounds.find(x=>x.status==='upcoming')?.round||rounds[0]?.round||1);
  $('roundBig').value=first;
  $('roundTitle').textContent='Caricamento analisi giornata…';
  await loadRound(first);
  loadNews();
}
async function loadRound(n){
  selectedRound=n;
  $('roundTitle').textContent='Caricamento analisi della giornata…';
  $('roundRows').innerHTML='<tr><td colspan="20">Analisi in corso…</td></tr>';
  try{
    const j=await api('/api/round/'+encodeURIComponent(n));
    const rd=rounds.find(x=>x.round===n);
    if(rd)rd.matches=j.matches||[];
    renderRound(n);
  }catch(e){
    $('roundTitle').textContent='Errore caricamento giornata';
    $('roundRows').innerHTML='<tr><td colspan="20">Errore: '+e.message+'</td></tr>';
  }
}
function buildRounds(){const opts=rounds.map(r=>`<option value="${r.round}">Giornata ${r.round} · ${r.status==='upcoming'?'PROSSIMA':r.status==='played'?'giocata':'futura'}</option>`).join('');$('roundBig').innerHTML=opts;$('playerMatch').innerHTML=matches.map((x,i)=>`<option value="${i}">G${x.round||''} · ${x.home}–${x.away}</option>`).join('')}
window.openMatch=async(d,h,a)=>{try{const j=await api(`/api/match?date=${encodeURIComponent(d)}&home=${encodeURIComponent(h)}&away=${encodeURIComponent(a)}`);const x=j.match;const av=x.availability||{};const abs=(av.details||[]).filter(z=>z.player).map(z=>`${z.team}: ${z.player} (${z.role||'ruolo n/d'}) · ${z.type||''} ${z.reason||''} · impatto ${z.importance||'—'}`);const nw=(av.details||[]).filter(z=>z.news).map(z=>`${z.team}: ${z.news}`);const odds=Object.entries(x.odds||{}).map(([k,v])=>`${k}: ${v}`).join(' · ')||'non disponibili';const shots=(x.shots_analysis||[]).map(a=>`${a.label} ${a.direction} ${a.line}: ${a.prob}%${a.odd?' · quota '+a.odd:''}`).join('\n')||'non disponibili';const hc=x.half_analysis||{};const htxt=hc.available?`1T ${hc.home?.first_gf?.toFixed?.(2)??'—'}-${hc.away?.first_gf?.toFixed?.(2)??'—'} gol medi · xG ${hc.home?.first_xg?.toFixed?.(2)??'—'}-${hc.away?.first_xg?.toFixed?.(2)??'—'} · tiri ${hc.home?.first_shots?.toFixed?.(1)??'—'}-${hc.away?.first_shots?.toFixed?.(1)??'—'} · SoT ${hc.home?.first_sot?.toFixed?.(1)??'—'}-${hc.away?.first_sot?.toFixed?.(1)??'—'}\n2T ${hc.home?.second_gf?.toFixed?.(2)??'—'}-${hc.away?.second_gf?.toFixed?.(2)??'—'} gol medi · xG ${hc.home?.second_xg?.toFixed?.(2)??'—'}-${hc.away?.second_xg?.toFixed?.(2)??'—'} · tiri ${hc.home?.second_shots?.toFixed?.(1)??'—'}-${hc.away?.second_shots?.toFixed?.(1)??'—'} · SoT ${hc.home?.second_sot?.toFixed?.(1)??'—'}-${hc.away?.second_sot?.toFixed?.(1)??'—'}\nStart index ${Number(hc.home?.start_index||0).toFixed(2)} / ${Number(hc.away?.start_index||0).toFixed(2)} · 2T index ${Number(hc.home?.second_index||0).toFixed(2)} / ${Number(hc.away?.second_index||0).toFixed(2)} · campione ${hc.sample}`:'non disponibile';alert(`${x.home} – ${x.away}\n\nPICK 1X2: ${x.pick1x2}\nBEST: ${x.best}${x.bestp!=null?' '+x.bestp+'%':''}${x.best_odd?' · quota '+x.best_odd:''}${x.edge!=null?' · value '+x.edge+'%':''}\nxG previsto: ${x.xgh} – ${x.xga}\nQualità dati: ${x.data_quality?.level||'—'} · xG verificati ${x.data_quality?.verified_xg??0}\n\n1° / 2° TEMPO\n${htxt}\n\nSHOTS ANALYSIS\n${shots}\n\nQUOTE DI RIFERIMENTO (${x.bookmaker||'provider'}):\n${odds}\n\nASSENZE / NEWS CHE INFLUENZANO IL MODELLO:\n${abs.concat(nw).slice(0,10).join('\n')||'Nessun segnale affidabile disponibile.'}\n\nANALISI:\n${(x.reasons||[]).join('\n')}\n\nCandidate 75–85%:\n${x.candidates?.length?x.candidates.map(c=>c.market+' '+c.prob+'% · fair '+c.fair+(c.odd?' · quota '+c.odd:'')).join('\n'):'NO BET'}`)}catch(e){alert(e.message)}};
function fillSelection(){const m=$('market').value;let a=[];if(m==='1X2')a=['1','X','2'];else if(m==='DC')a=['1X','X2','12'];else if(m==='OU')a=['O1.5','O2.5','O3.5','U2.5','U3.5'];else if(m==='BTTS')a=['GG','NG'];else if(m==='MG')a=['MG1-2','MG1-3','MG1-4','MG2-3','MG2-4','MG2-5','MG3-4','MG3-5','MG3-6','MG4-5','MG4-6','MGH1-2','MGH1-3','MGH1-4','MGH2-3','MGH2-4','MGH2-5','MGH3-4','MGH3-5','MGH3-6','MGH4-5','MGH4-6','MGA1-2','MGA1-3','MGA1-4','MGA2-3','MGA2-4','MGA2-5','MGA3-4','MGA3-5','MGA3-6','MGA4-5','MGA4-6'];else if(m==='COMBO')a=['1X+O1.5','X2+O1.5','1X+U3.5','X2+U3.5','12+O1.5','GG+O2.5','NG+U3.5'];$('targetWrap').classList.toggle('hidden',m==='overview');$('selection').innerHTML='<option value="">Tutti</option>'+a.map(x=>`<option value="${x}">${x.startsWith('MGH')?'Casa · '+x.slice(3):x.startsWith('MGA')?'Trasferta · '+x.slice(3):x}</option>`).join('');renderRound(+$('roundBig').value)}
function xHasOdds(ms,market){return ms.some(x=>x.odds&&x.odds[market]!=null)}
function renderRound(n){
  selectedRound=n;
  const rd=rounds.find(x=>x.round===n);
  $('roundTitle').textContent=rd?`Giornata ${n} · ${rd.matches.length} partite · ${rd.status}`:'';
  const market=$('market').value, sel=$('selection').value, ms=rd?rd.matches:[];
  let cols;
  if(market==='overview') cols=[['1','1'],['X','X'],['2','2'],['O2.5','O2.5'],['GG','GG'],['BEST','BEST']];
  else if(market==='1X2') cols=sel?[[sel,sel],['BEST','BEST']]:[['1','1'],['X','X'],['2','2'],['BEST','BEST']];
  else if(market==='DC') cols=sel?[[sel,sel],['BEST','BEST']]:[['1X','1X'],['X2','X2'],['12','12'],['BEST','BEST']];
  else if(market==='OU') cols=sel?[[sel,sel],['BEST','BEST']]:[['O1.5','O1.5'],['O2.5','O2.5'],['O3.5','O3.5'],['U2.5','U2.5'],['U3.5','U3.5'],['BEST','BEST']];
  else if(market==='BTTS') cols=sel?[[sel,sel],['BEST','BEST']]:[['GG','GG'],['NG','NG'],['BEST','BEST']];
  else if(market==='MG') cols=sel?[[sel,sel],['BEST','BEST']]:[['MG1-2','MG1-2'],['MG1-3','MG1-3'],['MG1-4','MG1-4'],['MG2-3','MG2-3'],['MG2-4','MG2-4'],['MG2-5','MG2-5'],['MG3-4','MG3-4'],['MG3-5','MG3-5'],['MG3-6','MG3-6'],['MG4-5','MG4-5'],['MG4-6','MG4-6'],['BEST','BEST']];
  else if(market==='COMBO') cols=sel?[[sel,sel],['BEST','BEST']]:[['1X+O1.5','1X+O1.5'],['X2+O1.5','X2+O1.5'],['1X+U3.5','1X+U3.5'],['X2+U3.5','X2+U3.5'],['12+O1.5','12+O1.5'],['GG+O2.5','GG+O2.5'],['NG+U3.5','NG+U3.5'],['BEST','BEST']];
  else cols=[['BEST','BEST']];
  cols.push(['SHOTS','SHOTS']);
  $('roundHead').innerHTML='<tr><th>Partita</th>'+cols.map(c=>'<th>'+c[1]+(c[0]!=='BEST'&&c[0]!=='SHOTS'&&xHasOdds(ms,c[0])?' <small class="bookHead">QUOTA</small>':'')+'</th>').join('')+'</tr>';
  const rows=ms.map(x=>{
    const cells=cols.map(c=>{
      if(c[0]==='BEST'){const q=x.best_odd;const fair=x.fair;const info=q?('Quota '+Number(q).toFixed(2)+(x.edge!=null?' · Value '+(x.edge>0?'+':'')+Number(x.edge).toFixed(1)+'%':'')):('MODEL ONLY · fair '+(fair??'—'));return '<td class="bestCell"><span class="bestPick">🟢 '+x.best+' · '+(x.bestp??'—')+'%</span><br><small class="bestLabel">'+info+'</small></td>';}
      if(c[0]==='SHOTS'){const sa=x.shots_analysis||[];const show=sa.slice(0,4).map(a=>`<div><b>${a.label}</b> ${a.direction} ${a.line}: ${a.prob}%${a.odd?' · '+Number(a.odd).toFixed(2):''}</div>`).join('');const hc=x.half_analysis||{};const half=hc.available?`<div class="halfMini"><b>1T start</b> ${Number(hc.home?.start_index||0).toFixed(2)} casa / ${Number(hc.away?.start_index||0).toFixed(2)} trasf. · <b>2T</b> ${Number(hc.home?.second_index||0).toFixed(2)} / ${Number(hc.away?.second_index||0).toFixed(2)} · ${hc.sample} match</div>`:'';return '<td class="shotsCell">'+half+(show||'—')+'</td>';}
      const q=x.odds?.[c[0]];
      if(q){const model=Number(x.m[c[0]]);const implied=(1/Number(q))*100;const diff=model-implied;const sign=diff>0?'+':'';return '<td><b>'+pct(model)+'</b><br><small class="bookOdd">'+(x.bookmaker||'Reference')+' '+Number(q).toFixed(2)+'</small><br><small class="impliedOdd">Imp. '+implied.toFixed(1)+'% · '+sign+diff.toFixed(1)+' pt</small></td>';}
      return '<td><b>'+pct(x.m[c[0]])+'</b></td>';
    }).join('');
    return `<tr><td><button class="matchLink" onclick='openMatch(${JSON.stringify(x.date)},${JSON.stringify(x.home)},${JSON.stringify(x.away)})'>${x.home} – ${x.away}</button><br><small>${x.date}</small></td>${cells}</tr>`;
  }).join('');
  $('roundRows').innerHTML=rows || '<tr><td colspan="'+(cols.length+1)+'">Nessun risultato.</td></tr>';
}

async function loadTeams(){const j=await api('/api/teams');$('teamSelect').innerHTML='<option value="">Seleziona squadra</option>'+j.teams.map(t=>`<option>${t}</option>`).join('')}
async function loadTeam(){const t=$('teamSelect').value;if(!t){$('teamCard').innerHTML='Seleziona una squadra.';return}const view=$('teamView').value,period=+$('teamPeriod').value,venue=$('teamVenue').value;const j=await api('/api/team/'+encodeURIComponent(t)+'?n='+period+'&venue='+encodeURIComponent(venue));renderTeam(j,view,venue)}
function metric(v,d=2){return v==null?'—':Number(v).toFixed(d)}
function teamRows(j,venue){return (j.matches||[]).filter(x=>venue==='all'||x.team_side===venue)}
function renderTeam(j,view,venue){const p=j.profile||{},rows=teamRows(j,venue),title=j.team;const venueLabel=venue==='home'?'Solo casa':venue==='away'?'Solo trasferta':'Casa + trasferta';const stat=(label,value,note='')=>`<div class="teamMetric"><span>${label}</span><b>${value}</b><small>${note}</small></div>`;let html='';if(view==='overview'){html=`<div class="teamTop"><div><h2>${title}</h2><p>${venueLabel} · ultime ${p.matches} · forma ${(p.form*100).toFixed(0)}% · ${p.verified_matches||0} partite con statistiche verificate</p></div></div><div class="teamMetrics">${stat('Gol fatti',metric(p.gf),'media')}${stat('Gol subiti',metric(p.ga),'media')}${stat('xG',metric(p.xg),'media · '+(p.xg_source||'—'))}${stat('xGA',metric(p.xg_against),'media · '+(p.xg_source||'—'))}${stat('Tiri',metric(p.shots),'media')}${stat('Tiri in porta',metric(p.sot),'media')}${stat('Corner',metric(p.corners),'media')}${stat('Possesso',p.possession!=null?metric(p.possession,1)+'%':'—','media')}${stat('Tiri fuori',metric(p.shots_off),'media')}${stat('Tiri bloccati',metric(p.blocked),'media')}${stat('Gialli',metric(p.yellow),'media')}</div>`}else if(view==='goals'){html=`<h2>${title} · Gol & forma</h2><div class="teamMetrics">${stat('Gol fatti',metric(p.gf),'media ultime')}${stat('Gol subiti',metric(p.ga),'media ultime')}${stat('Casa GF/GA',metric(p.home_gf)+' / '+metric(p.home_ga))}${stat('Trasferta GF/GA',metric(p.away_gf)+' / '+metric(p.away_ga))}${stat('Forma',((p.form||0)*100).toFixed(0)+'%','punti recenti')}</div>`}else if(view==='xg'){html=`<h2>${title} · xG</h2><div class="teamMetrics">${stat('xG',metric(p.xg),'media · '+(p.xg_source||'—'))}${stat('xGA',metric(p.xg_against),'media · '+(p.xg_source||'—'))}${stat('Casa xGF/xGA',metric(p.home_xg)+' / '+metric(p.home_xga))}${stat('Trasferta xGF/xGA',metric(p.away_xg)+' / '+metric(p.away_xga))}${stat('Match xG',p.xg_matches||0,'verificati: '+(p.xg_verified_matches||0))}</div>`}else if(view==='shots'){html=`<h2>${title} · Tiri</h2><div class="teamMetrics">${stat('Tiri',metric(p.shots),'media')}${stat('Tiri avversari',metric(p.shots_against),'media')}${stat('Tiri in porta',metric(p.sot),'media')}${stat('Tiri in porta avv.',metric(p.sot_against),'media')}${stat('Tiri fuori',metric(p.shots_off),'media')}${stat('Tiri fuori avv.',metric(p.shots_off_against),'media')}${stat('Bloccati',metric(p.blocked),'media')}${stat('Bloccati avv.',metric(p.blocked_against),'media')}</div>`}else if(view==='corners'){html=`<h2>${title} · Corner</h2><div class="teamMetrics">${stat('Corner',metric(p.corners),'media')}${stat('Corner avversari',metric(p.corners_against),'media')}</div>`}else if(view==='possession'){html=`<h2>${title} · Possesso & volume</h2><div class="teamMetrics">${stat('Possesso',p.possession!=null?metric(p.possession,1)+'%':'—','media')}${stat('Possesso avversari',p.possession_against!=null?metric(p.possession_against,1)+'%':'—','media')}${stat('Tiri fuori',metric(p.shots_off),'media')}${stat('Tiri fuori avv.',metric(p.shots_off_against),'media')}${stat('Tiri bloccati',metric(p.blocked),'media')}${stat('Tiri bloccati avv.',metric(p.blocked_against),'media')}</div>`}else if(view==='discipline'){html=`<h2>${title} · Falli & cartellini</h2><div class="teamMetrics">${stat('Falli',metric(p.fouls),'media')}${stat('Falli avversari',metric(p.fouls_against),'media')}${stat('Gialli',metric(p.yellow),'media')}${stat('Gialli avversari',metric(p.yellow_against),'media')}</div>`}else{html=`<h2>${title} · Ultime partite</h2><div class="tablewrap"><table><thead><tr><th>Data</th><th>Partita</th><th>Ris.</th><th>Tiri</th><th>Tiri porta</th><th>Corner</th><th>xG</th><th>Falli</th><th>Gialli</th><th>Fonte</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${x.date}</td><td>${x.home} – ${x.away}</td><td>${x.hg??'—'}–${x.ag??'—'}</td><td>${x.team_shots??'—'} <small>(avv. ${x.opponent_shots??'—'})</small></td><td>${x.team_sot??'—'} <small>(avv. ${x.opponent_sot??'—'})</small></td><td>${x.team_corners??'—'} <small>(avv. ${x.opponent_corners??'—'})</small></td><td>${x.team_xg!=null?Number(x.team_xg).toFixed(2):'—'} <small>(${x.team_xg_source||'—'})</small></td><td>${x.team_fouls??'—'}</td><td>${x.team_yellow??'—'}</td><td>${x.stats_source==='SofaScore'?'SofaScore':'—'}</td></tr>`).join('')}</tbody></table></div>`}$('teamCard').innerHTML=html}
$('roundBig').onchange=e=>loadRound(+e.target.value);$('market').onchange=fillSelection;$('selection').onchange=()=>renderRound(selectedRound);$('teamSelect').onchange=loadTeam;$('teamView').onchange=loadTeam;$('teamPeriod').onchange=loadTeam;$('teamVenue').onchange=loadTeam;

let playerLiveTimer=null;
$('loadPlayers').onclick=async()=>{
const x=matches[+$('playerMatch').value];if(!x)return;
if(playerLiveTimer){clearInterval(playerLiveTimer);playerLiveTimer=null;}
$('playerContext').textContent='Sincronizzazione storico giocatori e dati live…';
try{
const j=await api('/api/player-props?date='+encodeURIComponent(x.date)+'&home='+encodeURIComponent(x.home)+'&away='+encodeURIComponent(x.away));
const d=j.data;const live=d.liveMatch||{};
$('playerContext').innerHTML='<h3>'+x.home+' – '+x.away+'</h3><p>Fonte: '+(d.source||'')+' · arbitro: '+(d.referee||'non disponibile')+' · Probabili formazioni: '+(d.probableLineupsAvailable?'disponibili':'non disponibili')+' · Ufficiali: '+(d.lineupsAvailable?'disponibili':'non ancora disponibili')+' · Aggiornamento: '+(d.probableLineupsUpdated||'non indicato')+'</p><p class="muted">'+(d.notes||[]).join(' ')+'</p>';
if(!d.pitchAPIConfigured)$('playerContext').innerHTML+='<p class="muted">PitchAPI non è configurata. Crea la chiave gratuita e aggiungi PITCHAPI_API_KEY=la_tua_chiave nel file config.env; poi riavvia start.command e premi “Verifica PitchAPI”. Non incollare la chiave in chat.</p>';if(live.reason==='API_FOOTBALL_KEY non configurata'&&d.pitchAPIConfigured===false)$('playerContext').innerHTML+='<p class="muted">La fonte di riserva API-Football non è configurata; PitchAPI può funzionare in modo indipendente.</p>';if(d.pitchAPIStatus&&d.pitchAPIStatus.configured&&!d.pitchAPIStatus.ok)$('playerContext').innerHTML+='<p class="muted">Diagnostica PitchAPI: '+String(d.pitchAPIStatus.error||'nessuna statistica storica corrispondente').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</p>';
const liveText=v=>v===null||v===undefined||v===''?'—':String(v);
const liveEsc=v=>liveText(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
let livePanel='';
if(live.isLive){
const hs=Object.fromEntries((live.teamStats&&live.teamStats.home||[]).map(z=>[z.label,z.value]));
const as=Object.fromEntries((live.teamStats&&live.teamStats.away||[]).map(z=>[z.label,z.value]));
const labels=[...new Set([...(live.teamStats&&live.teamStats.home||[]).map(z=>z.label),...(live.teamStats&&live.teamStats.away||[]).map(z=>z.label)])];
const teamRows=labels.map(label=>'<tr><td>'+liveEsc(label)+'</td><td>'+liveEsc(hs[label])+'</td><td>'+liveEsc(as[label])+'</td></tr>').join('');
const lp=live.players||[];
const playerRows=lp.map(p=>'<tr><td><b>'+liveEsc(p.name)+'</b></td><td>'+liveEsc(p.team||p.side)+'</td><td>'+liveEsc(p.minutes)+'</td><td>'+liveEsc(p.shots)+'</td><td>'+liveEsc(p.sot)+'</td><td>'+liveEsc(p.fouls)+'</td><td>'+liveEsc(p.fouled)+'</td><td>'+liveEsc(p.yellow)+'</td><td>'+liveEsc(p.rating)+'</td></tr>').join('');
livePanel='<section class="card" style="margin-bottom:14px"><h3>LIVE · '+liveEsc(live.home)+' '+liveEsc(live.homeGoals)+' – '+liveEsc(live.awayGoals)+' '+liveEsc(live.away)+'</h3><p class="muted">'+liveEsc(live.status)+(live.elapsed!==null&&live.elapsed!==undefined?' · '+liveEsc(live.elapsed)+"'":'')+' · Fonte: '+liveEsc(live.source)+' · aggiornato '+liveEsc(live.updated)+' · Aggiornamento automatico ogni 5 minuti.</p><h4>Statistiche squadra</h4><table><thead><tr><th>Statistica</th><th>'+liveEsc(live.home)+'</th><th>'+liveEsc(live.away)+'</th></tr></thead><tbody>'+(teamRows||'<tr><td colspan="3">Statistiche di squadra non ancora disponibili.</td></tr>')+'</tbody></table><h4 style="margin-top:16px">Statistiche giocatori live</h4>'+(playerRows?'<table><thead><tr><th>Giocatore</th><th>Squadra</th><th>Min</th><th>Tiri</th><th>SoT</th><th>Falli</th><th>Falli subiti</th><th>Gialli</th><th>Voto</th></tr></thead><tbody>'+playerRows+'</tbody></table>':'<p class="muted">Statistiche individuali non ancora pubblicate dal provider per questa partita.</p>')+'</section>';
}
$('playerTable').innerHTML=livePanel+(d.players?.length?`<table><thead><tr><th>Giocatore</th><th>Squadra</th><th>Ruolo</th><th>Stato</th><th>Storico</th><th>Titolarità</th><th>Min attesi</th><th>Falli/90</th><th>Falli subiti/90</th><th>Tiri/90</th><th>SoT/90</th><th>Gialli/90</th><th>xG/90</th><th>Assist/90</th><th>Falli ≥1</th><th>Falli subiti ≥1</th><th>Tiri ≥1</th><th>SoT ≥1</th><th>Ammonito ≥1</th><th>Gol ≥1</th></tr></thead><tbody>${d.players.map(p=>{const q=Object.fromEntries((p.propCandidates||[]).map(z=>[z.market,z.prob]));return `<tr><td><b>${p.name}</b></td><td>${p.team}</td><td>${p.position||'—'}</td><td>${p.lineupStatus||'—'}</td><td>${p.dataBasis||'—'}</td><td>${p.starterProbability!=null?p.starterProbability+'%':'—'}</td><td>${p.expectedMinutes||'—'}</td><td>${p.history?.fouls90!=null?Number(p.history.fouls90).toFixed(2):'—'}</td><td>${p.history?.fouled90!=null?Number(p.history.fouled90).toFixed(2):'—'}</td><td>${p.history?.shots90!=null?Number(p.history.shots90).toFixed(2):'—'}</td><td>${p.history?.sot90!=null?Number(p.history.sot90).toFixed(2):'—'}</td><td>${p.history?.cards90!=null?Number(p.history.cards90).toFixed(2):'—'}</td><td>${p.history?.xg90!=null?Number(p.history.xg90).toFixed(2):'—'}</td><td>${p.history?.assists90!=null?Number(p.history.assists90).toFixed(2):'—'}</td><td>${q['Falli commessi O0.5']!=null?q['Falli commessi O0.5']+'%':'—'}</td><td>${q['Falli subiti O0.5']!=null?q['Falli subiti O0.5']+'%':'—'}</td><td>${q['Tiri O0.5']!=null?q['Tiri O0.5']+'%':'—'}</td><td>${q['Tiri in porta O0.5']!=null?q['Tiri in porta O0.5']+'%':'—'}</td><td>${q['Cartellini O0.5']!=null?q['Cartellini O0.5']+'%':'—'}</td><td>${q['Gol O0.5']!=null?q['Gol O0.5']+'%':'—'}</td></tr>`}).join('')}</tbody></table>`:'<div class="card">Nessuno storico giocatore reale sufficiente per questa partita.</div>');if(live.isLive)playerLiveTimer=setInterval(()=>{const node=document.querySelector('#players');if(!document.hidden&&node&&node.classList.contains('active'))$('loadPlayers').click();},300000);
}catch(e){$('playerContext').textContent='Errore: '+e.message}}
const testPitchApi=$('testPitchApi');
if(testPitchApi){
  testPitchApi.onclick=async()=>{
    testPitchApi.disabled=true;testPitchApi.textContent='Verifica in corso…';
    $('playerContext').textContent='Verifico la chiave e la copertura Serie A di PitchAPI…';
    try{
      const response=await api('/api/pitchapi-status');
      const d=response.data||{};
      const state=d.ok?'Connessione riuscita':'Connessione non verificata';
      const details=[
        d.message||'Nessun dettaglio restituito.',
        d.league?('Campionato: '+d.league):'',
        d.season?('Stagione: '+d.season):'',
        d.playedMatches!=null?('Partite concluse disponibili: '+d.playedMatches):'',
        d.upcomingMatches!=null?('Partite future disponibili: '+d.upcomingMatches):'',
        d.error?('Dettaglio errore: '+(typeof d.error==='string'?d.error:JSON.stringify(d.error))):''
      ].filter(Boolean);
      $('playerContext').innerHTML='<h3>Test PitchAPI · '+state+'</h3><p>'+details.map(s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')).join('<br>')+'</p><p class="muted">Quando la connessione è attiva, clicca “Analizza giocatori” per recuperare lo storico della partita selezionata.</p>';
    }catch(e){
      $('playerContext').textContent='Test PitchAPI fallito: '+e.message;
    }finally{
      testPitchApi.disabled=false;testPitchApi.textContent='Verifica PitchAPI';
    }
  };
}
async function loadNews(){try{const j=await api('/api/news');const items=j.items||[];const card=n=>{const dt=n.date?new Date(n.date).toLocaleDateString('it-IT',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'';return `<article class="newsCard"><div class="newsTop"><span class="newsBadge">CALCIO</span><span class="newsDate">${dt}</span></div><a href="${n.link}" target="_blank" rel="noreferrer"><h3>${n.title}</h3></a><div class="newsSource">${n.source||'News'} <span>↗</span></div></article>`};$('dashboardNews').innerHTML=items.length?items.slice(0,6).map(card).join(''):'<div class="emptyNews">Feed news non disponibile in questo momento.</div>';$('newsList').innerHTML=items.length?items.map(card).join(''):'<div class="card">Feed news non disponibile in questo momento.</div>'}catch(e){$('dashboardNews').innerHTML='<div class="emptyNews">Feed news non disponibile.</div>';if($('newsList'))$('newsList').innerHTML='<div class="card">Feed news non disponibile.</div>'}}
['dashboardNewsRefresh','newsRefresh'].forEach(id=>{const b=$(id);if(b)b.onclick=loadNews});$('refresh').onclick=async()=>{const b=$('refresh');b.disabled=true;b.textContent='⏳ Aggiornamento avviato…';try{const r=await api('/api/refresh',{method:'POST'});b.textContent=r.data?.status==='already_running'?'⏳ Aggiornamento già in corso…':'✓ Aggiornamento in background';setTimeout(()=>{b.textContent='↻ Aggiorna dati';b.disabled=false},1800)}catch(e){b.textContent='⚠ Errore aggiornamento';b.disabled=false;alert('Aggiornamento non riuscito: '+e.message)}};tabs();fillSelection();load().catch(e=>alert(e.message));