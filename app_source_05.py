    verified=sum(1 for r in relevant if stats_verified(r))
    xg_verified=sum(1 for r in relevant if r.get('xgh') is not None and r.get('xga') is not None)
    level='high' if verified>=4 and xg_verified>=4 and n>=5 else 'medium' if verified>=2 else 'limited'
    return {'matches':n,'verified_stats':verified,'verified_xg':xg_verified,'level':level}

def model_obj(d,r):
    h,a=xg(d,r['home'],r['away'])
    availability=availability_context(d,r) if r.get('date','')>=date.today().isoformat() else {'home_attack_loss':0.0,'home_defense_loss':0.0,'away_attack_loss':0.0,'away_defense_loss':0.0,'details':[],'available':False,'prediction':None}
    # Availability/news adjustment: modest, bounded, and applied to the scoring lambdas.
    # Defensive absences hurt the affected side's defence; attacking absences hurt attack.
    # Without a confirmed role we use a conservative generic penalty.
    h *= math.exp(-0.10*availability.get('home_attack_loss',0.0) + 0.12*availability.get('away_defense_loss',0.0))
    a *= math.exp(-0.10*availability.get('away_attack_loss',0.0) + 0.12*availability.get('home_defense_loss',0.0))
    h=max(.10,min(4.5,h));a=max(.10,min(4.0,a))
    # Blend a small amount of API-Football's independent prediction only when valid.
    pred=availability.get('prediction') or {}
    pct=(pred.get('predictions') or {}).get('percent') if isinstance(pred,dict) else None
    half_ctx=half_context_for_match(r)
    p=markets(h,a)
    p.update(volume_markets(d,r))
    p.update(half_market_probs(half_ctx))
    if isinstance(pct,dict):
        try:
            api_p={'1':float(str(pct.get('home','')).replace('%',''))/100,'X':float(str(pct.get('draw','')).replace('%',''))/100,'2':float(str(pct.get('away','')).replace('%',''))/100}
            if sum(api_p.values())>0.5:
                for k in ('1','X','2'):p[k]=0.88*p[k]+0.12*api_p[k]
                s=sum(p[k] for k in ('1','X','2'));
                for k in ('1','X','2'):p[k]/=s
        except Exception:pass
    fixture_odds=odds_for(r)
    if not fixture_odds:
        fixture_odds=next((odds_for(x) for x in d.get('fixtures',[]) if x.get('div')=='I1' and x['date']==r['date'] and x['home']==r['home'] and x['away']==r['away']),{})
    best,ranked=best_engine(d,r,p,fixture_odds);coupon=coupon_candidates({k:v for k,v in p.items() if not k.startswith(('TS_','HS_','AS_','SOT_','HSOT_','ASOT_','C_','HC_','AC_'))},fixture_odds,ranked=[])
    shot_report=shots_analysis(d,r,fixture_odds)
    pick=max(('1','X','2'),key=lambda k:p[k]);q=data_quality(d,r['home'],r['away'])
    reasons=scenario_reasons(d,r,best)
    return {'date':r['date'],'time':r.get('time',''),'home':r['home'],'away':r['away'],'round':r.get('round'),'xgh':round(h,2),'xga':round(a,2),
            'pick1x2':pick,'m':{k:round(v*100,1) for k,v in p.items()},
            'best':best['label'] if best else 'NO BET','best_market':best['market'] if best else None,'bestp':best['prob'] if best else None,'fair':best['fair'] if best else None,'best_odd':best['odd'] if best else None,'best_mean':best.get('mean') if best else None,'best_margin':best.get('margin') if best else None,'best_kind':best.get('kind') if best else None,
            'book':fixture_odds.get(best['market']) if best else None,
            'bookmaker':fixture_odds.get('_bookmaker'),
            'odds_source':fixture_odds.get('_odds_source','Football-Data / reference'),
            'odds':{k:v for k,v in fixture_odds.items() if not k.startswith('_')},
            'edge':best.get('edge') if best else None,
            'candidates':coupon[:12],'best_ranked':ranked[:12],'shots_analysis':shot_report,'half_analysis':half_ctx,'reasons':reasons,'data_quality':q,'availability':availability,
            'profiles':{'home':team_profile(d,r['home']),'away':team_profile(d,r['away'])}}

# ---- optional live context: public SofaScore endpoints; cached and never required for core model ----
def sofa_cache_load():
    try:return json.load(open(SOFA_CACHE,encoding='utf-8'))
    except:return {}
def sofa_cache_save(c):json.dump(c,open(SOFA_CACHE,'w',encoding='utf-8'),ensure_ascii=False)
def sofa_get(path,ttl=21600,force=False):
    c=sofa_cache_load();key=path;now=time.time();v=c.get(key)
    if not force and v and now-v.get('ts',0)<ttl:return v.get('data')
    try:
        data=http_json(SOFA+path);c[key]={'ts':now,'data':data};sofa_cache_save(c);return data
    except Exception:
        return None

def sofa_event_for(r):
    # Static calendars can lag behind the real fixture date. Search the target
    # date and a small +/- 3 day window, then synchronize the record.
    target=date.fromisoformat(r['date'])
    def nm(x):return norm_team(x)
    for delta in (0,-1,1,-2,2,-3,3):
        day=(target+timedelta(days=delta)).isoformat()
        data=sofa_get('/sport/football/scheduled-events/'+day,ttl=900)
        if not data:continue
        for e in data.get('events',[]):
            h=nm(e.get('homeTeam',{}).get('name'));a=nm(e.get('awayTeam',{}).get('name'))
            # Normalize both provider names and our schedule names; providers may
            # append club suffixes such as "FC" or use alternate spellings.
            rh=nm(r.get('home'));ra=nm(r.get('away'))
            def equivalent(x,y):
                if x==y:return True
                strip=lambda s: re.sub(r'\b(fc|cf|ssc|calcio|1907|1919|1927|1928|1912)\b','',s).strip()
                return strip(x)==strip(y)
            if equivalent(h,rh) and equivalent(a,ra):
                r['date']=day
                ts=e.get('startTimestamp')
                if ts:
                    try:
                        from datetime import timezone
                        from zoneinfo import ZoneInfo
                        z=datetime.fromtimestamp(int(ts),tz=timezone.utc).astimezone(ZoneInfo('Europe/Rome'))
                        r['time']=z.strftime('%H:%M')
                    except Exception:pass
                return e
    return None

def player_stats_from_lineup(lineup,side):
    rows=[]
    for item in (lineup.get(side,{}).get('players',[]) if lineup else []):
        p=item.get('player',{});s=item.get('statistics') or {};mins=s.get('minutesPlayed') or 0
        if not p.get('name'):continue
        rows.append({'id':p.get('id'),'name':p.get('name'),'position':p.get('position'),'substitute':item.get('substitute',False),'minutes':mins,'fouls':s.get('fouls'),'fouled':s.get('wasFouled'),'shots':s.get('totalShots') or s.get('shots'),'sot':s.get('shotsOnTarget'),'cards':s.get('yellowCards',0) or 0,'goals':s.get('goals',0) or 0,'assists':s.get('assists',0) or 0})
    return rows

def player_history(team_id):
    # Prefer recent real match lineups. Read up to 24 finished matches so
    # missing data on one match does not wipe the whole player history.
    agg={};pages=[]
    for page in (0,1):
        data=sofa_get(f'/team/{team_id}/events/last/{page}',ttl=1800)
        evs=(data or {}).get('events',[])
        if not evs: break
        pages.extend(evs)
        if len(pages)>=24: break
    for e in pages[:24]:
        if e.get('status',{}).get('type')!='finished':continue
        lu=sofa_get(f"/event/{e['id']}/lineups",ttl=7*86400)
        if not lu:continue
        side='home' if e.get('homeTeam',{}).get('id')==team_id else 'away'
        for s in player_stats_from_lineup(lu,side):
            if not s['minutes']:continue
            a=agg.setdefault(s['id'],dict(s,apps=0,starts=0));a['apps']+=1
            if not s.get('substitute'): a['starts']+=1
            for k in ('minutes','fouls','fouled','shots','sot','cards','goals','assists'):
                if s.get(k) is not None:a[k]=(a.get(k) or 0)+(s.get(k) or 0)
    out=[]
    for a in agg.values():
        mins=a['minutes'] or 1
        a['fouls90']=round((a.get('fouls') or 0)/mins*90,2);a['fouled90']=round((a.get('fouled') or 0)/mins*90,2);a['shots90']=round((a.get('shots') or 0)/mins*90,2);a['sot90']=round((a.get('sot') or 0)/mins*90,2);a['cards90']=round((a.get('cards') or 0)/mins*90,2)
        a['starterPct']=round(100*(a.get('starts',0)/max(1,a.get('apps',0))),1)
        a['avgMinutes']=round(a.get('minutes',0)/max(1,a.get('apps',0)),1);out.append(a)
    return sorted(out,key=lambda x:x['minutes'],reverse=True)

def api_football_player_history(team_name):
    # Fallback primario: risolvi direttamente la squadra via API-Football.
    # Non dipendere dalla prima pagina del calendario, che può non contenere
    # la squadra richiesta e lasciare il Player Analyzer completamente vuoto.
    try:
        if not API_FOOTBALL_KEY:return []
        target=norm_team(team_name)
        team_data=api_football_get('/teams?name='+quote_plus(str(team_name))+'&league='+str(API_FOOTBALL_LEAGUE)+'&season=2026',ttl=24*3600) or {}
        team_rows=team_data.get('response') or []
        team_obj=next((x.get('team',{}) for x in team_rows
                       if norm_team((x.get('team') or {}).get('name',''))==target),None)
        if not team_obj and team_rows:
            team_obj=(team_rows[0].get('team') or {})
        tid=(team_obj or {}).get('id')
        if not tid:
            # Secondary fallback using any known fixture for the team.
            for fx in api_football_season_fixtures():
                th=norm_team((fx.get('teams') or {}).get('home',{}).get('name',''))
                ta=norm_team((fx.get('teams') or {}).get('away',{}).get('name',''))
                if target in (th,ta):
                    tid=((fx.get('teams') or {}).get('home',{}).get('id') if target==th
                         else (fx.get('teams') or {}).get('away',{}).get('id'))
                    if tid:break
        if not tid:return []
        # Fetch every available player page; the default page is only a partial roster.
        out=[]; page=1
        while page<=10:
            data=api_football_get(f'/players?league={API_FOOTBALL_LEAGUE}&season=2026&team={tid}&page={page}',ttl=6*3600) or {}
            rows=data.get('response') or []
            if not rows:break
            for row in rows:
                p=row.get('player') or {}; st=(row.get('statistics') or [{}])[0]
                g=st.get('games') or {}; mins=float(g.get('minutes') or 0); apps=int(g.get('appearences') or 0); starts=int(g.get('lineups') or 0)
                if mins<120 or not p.get('id'):continue
                shots=st.get('shots') or {}; fouls=st.get('fouls') or {}; cards=st.get('cards') or {}; goals=st.get('goals') or {}
                a={'id':p.get('id'),'name':p.get('name'),'position':g.get('position'),
                   'minutes':mins,'apps':apps,'starts':starts,'fouls':fouls.get('committed') or 0,
                   'fouled':fouls.get('drawn') or 0,'shots':shots.get('total') or 0,'sot':shots.get('on') or 0,
                   'cards':cards.get('yellow') or 0,'goals':goals.get('total') or 0,'assists':goals.get('assists') or 0}
                a['starterPct']=round(100*starts/max(1,apps),1);a['avgMinutes']=round(mins/max(1,apps),1)
                a['fouls90']=round(a['fouls']/mins*90,2);a['fouled90']=round(a['fouled']/mins*90,2);a['shots90']=round(a['shots']/mins*90,2);a['sot90']=round(a['sot']/mins*90,2);a['cards90']=round(a['cards']/mins*90,2)
                out.append(a)
            if len(rows)<20:break
            page+=1
        return sorted(out,key=lambda x:x['minutes'],reverse=True)
    except Exception:
        return []

def fantacalcio_probable_lineups():
    """Read public probable starters/substitutes and starter probabilities from Fantacalcio.it."""
    from html.parser import HTMLParser
    cache=_context_cache_load();key='fantacalcio_probable_lineups_v1';now=time.time();cached=cache.get(key)
    if cached and now-cached.get('ts',0)<1800:
        return cached.get('data') or {}
    url='https://www.fantacalcio.it/probabili-formazioni-serie-a'
    class LineupParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_h3=False;self.h3=[];self.team=None;self.in_a=False;self.anchor=[]
            self.last_player=None;self.bench=False;self.data={};self.updated=''
        def handle_starttag(self,tag,attrs):
            if tag.lower()=='h3':
                self.in_h3=True;self.h3=[]
            elif tag.lower()=='a' and self.team:
                self.in_a=True;self.anchor=[]
        def handle_endtag(self,tag):
            if tag.lower()=='h3':
                name=' '.join(' '.join(self.h3).split())
                self.in_h3=False
                norm=norm_team(name)
                aliases={'ac milan':'milan','as roma':'roma','inter milan':'inter','ssc napoli':'napoli'}
                norm=aliases.get(norm,norm)
                known={norm_team(x) for x in ('Atalanta','Bologna','Cagliari','Como','Cremonese','Fiorentina','Genoa','Inter','Juventus','Lazio','Lecce','Milan','Napoli','Parma','Pisa','Roma','Sassuolo','Torino','Udinese','Venezia','Verona')}
                self.team=norm if norm in known else None
                self.bench=False;self.last_player=None
            elif tag.lower()=='a' and self.in_a:
                self.in_a=False
                name=' '.join(' '.join(self.anchor).split())
                if self.team and name and not name.endswith('%'):
                    self.last_player=name
        def handle_data(self,data):
            if self.in_h3:self.h3.append(data)
            if self.in_a:self.anchor.append(data)
            if not self.team:return
            txt=' '.join(data.split())
            if txt.lower()=='panchina':
                self.bench=True;self.last_player=None;return
            m=re.fullmatch(r'(\d{1,3})\s*%',txt)
            if m and self.last_player:
                self.data.setdefault(self.team,[]).append({
                    'name':self.last_player,'starterProbability':max(0,min(100,int(m.group(1)))),
                    'substitute':self.bench,'lineupStatus':'Panchina' if self.bench else 'Titolare probabile'
                })
                self.last_player=None
            if 'Ultimo aggiornamento' in txt:
                self.updated=txt.replace('Ultimo aggiornamento','').strip()
    try:
        raw=get(url)
        parser=LineupParser();parser.feed(raw.decode('utf-8','replace') if isinstance(raw,bytes) else str(raw))
        data={'teams':parser.data,'updated':parser.updated,'source':url}
        if sum(len(v) for v in parser.data.values())>=100:
            cache[key]={'ts':now,'data':data};_context_cache_save(cache)
            return data
        if cached and cached.get('data'):return cached['data']
        return data
    except Exception:
        return (cached or {}).get('data') or {}

def probable_lineup_for_team(team_name, source_data):
    target=norm_team(team_name)
    aliases={'ac milan':'milan','as roma':'roma','inter milan':'inter','ssc napoli':'napoli'}
    target=aliases.get(target,target)
    for name,players in (source_data.get('teams') or {}).items():
        if aliases.get(norm_team(name),norm_team(name))==target:
            return players
    return []

def sofa_team_id_for_name(team_name):
    """Resolve a SofaScore team ID independently of the upcoming fixture event."""
    target=norm_team(team_name)
    aliases={'milan':'ac milan','as roma':'roma','ssc napoli':'napoli','internazionale':'inter'}
    target=aliases.get(target.lower(),target)
    cache=_context_cache_load();key='sofa_team_id_'+re.sub(r'[^a-z0-9]+','_',target.lower()).strip('_')
    now=time.time();entry=cache.get(key)
    if entry and now-entry.get('ts',0)<7*86400 and entry.get('id'):
        return entry['id']
    queries=[team_name,target]
    for query in queries:
        data=sofa_get('/search/all?q='+quote_plus(str(query)),ttl=7*86400) or {}
        candidates=[]
        for item in (data.get('teams') or []):
            team=item.get('entity') if isinstance(item.get('entity'),dict) else item
            name=norm_team(team.get('name',''))
            short=norm_team(team.get('shortName',''))
            if name==target or short==target or name.lower()==str(team_name).lower():
                candidates.append(team)
        if candidates:
            team=candidates[0]
            tid=team.get('id')
            if tid:
                cache[key]={'ts':now,'id':tid,'name':team.get('name')}
                _context_cache_save(cache)
                return tid
    return None

def player_props(d,r):
    e=sofa_event_for(r)
    probable=fantacalcio_probable_lineups()
    probable_updated=probable.get('updated')
    result={'available':False,'source':'Fantacalcio.it + SofaScore + API-Football','eventId':e.get('id') if e else None,
            'referee':(e or {}).get('referee',{}).get('name'),'players':[],'notes':[],'lineupsAvailable':False,
            'probableLineupsAvailable':False,'probableLineupsUpdated':probable_updated,'probableLineupsSource':probable.get('source')}
    # SofaScore is the preferred source, but its scheduled-event endpoint can
    # temporarily omit a fixture. In that case continue with API-Football
    # historical player aggregates instead of returning an empty screen.
    lu=sofa_get(f"/event/{e['id']}/lineups",ttl=900) if e else None
    result['lineupsAvailable']=bool(lu)
    histories={}
    for side in ('home','away'):
        tid=(e or {}).get(side+'Team',{}).get('id')
        # The fixture endpoint can miss a match even when team match histories
        # are available. Resolve the club independently instead of abandoning
        # all foul/shot/card statistics just because the event was not found.
        if not tid:
            tid=sofa_team_id_for_name(r[side])
        hist_rows=player_history(tid) if tid else []
        if len(hist_rows)<3 and API_FOOTBALL_KEY:
            api_rows=api_football_player_history(r[side])
            if len(api_rows)>len(hist_rows):hist_rows=api_rows
        histories[side]={x['id']:x for x in hist_rows if x.get('id') is not None}
    if not e:
        result['notes'].append('SofaScore non ha restituito la partita: uso le probabili formazioni pubbliche e lo storico disponibile.')
    probable_candidates=[]
    for side,team in [('home',r['home']),('away',r['away'])]:
        for pp in probable_lineup_for_team(team,probable):
            probable_candidates.append(dict(pp,team=team,side=side,fromProbableSource=True))
    result['probableLineupsAvailable']=bool(probable_candidates)
    candidates=[]
    if not any(histories.get(side) for side in ('home','away')) and not lu and not probable_candidates:
        result['notes'].append('Nessun dato giocatori recuperabile. Verifica connessione e fonti dati.')
        return result

    
    if lu:
        for side,team in [('home',r['home']),('away',r['away'])]:
            for p in player_stats_from_lineup(lu,side):
                candidates.append(dict(p,team=team,side=side,fromProbableSource=False))
    elif probable_candidates:
        candidates.extend(probable_candidates)
    else:
        # Include all source-listed starters and substitutes; add historical players only
        # when the probable-lineup feed has no data for that team.
        for side,team in [('home',r['home']),('away',r['away'])]:
            if probable_lineup_for_team(team,probable):continue
            for p in sorted(histories.get(side,{}).values(),key=lambda x:x.get('minutes',0),reverse=True)[:25]:
                candidates.append({'id':p.get('id'),'name':p.get('name'),'position':p.get('position'),
                                   'substitute':False,'minutes':0,'team':team,'side':side,'lineupStatus':'Storico, probabile formazione non disponibile','starterProbability':float(p.get('starterPct') or 0),'fromProbableSource':False})

    for p in candidates:
        side_hist=histories.get(p.get('side'),{})
        hist=side_hist.get(p.get('id'))
        # Provider IDs differ; normalized name matching is the cross-provider fallback.
        if not hist and p.get('name'):
            pname=norm_team(p.get('name'))
            hist=next((v for v in side_hist.values() if norm_team(v.get('name',''))==pname),None)
            if not hist:
                # Probable-lineup feeds often abbreviate first names (e.g.
                # "Esposito F.P.") while statistics providers use full names.
                # Match on a unique surname/token only; never pick arbitrarily
                # when more than one historical player could match.
                tokens=[t for t in re.findall(r'[a-z0-9]+',pname.lower()) if len(t)>2]
                matches=[]
                for v in side_hist.values():
                    vname=norm_team(v.get('name','')).lower()
                    vtokens=[t for t in re.findall(r'[a-z0-9]+',vname) if len(t)>2]
                    if tokens and vtokens and (tokens[0] in vtokens or vtokens[-1] in tokens):
                        matches.append(v)
                if len(matches)==1:
                    hist=matches[0]
        if not hist or hist.get('minutes',0)<120:
            if p.get('fromProbableSource'):
                p['position']=p.get('position') or '—'
                p['starterProbability']=float(p.get('starterProbability') or 0)
                p['expectedMinutes']=None
                p['propCandidates']=[]
                p['dataBasis']='Probabile formazione Fantacalcio.it; storico statistiche non disponibile'
                result['players'].append(p)
            continue
        if p.get('fromProbableSource'):
            starter_pct=float(p.get('starterProbability') or 0.0)
            expected_min=max(5.0,min(90.0,float(hist.get('avgMinutes') or 0.0)))
        elif lu:
            starter=not bool(p.get('substitute',False)); starter_pct=100.0 if starter else 0.0; expected_min=78 if starter else 28
        else:
            starter_pct=float(hist.get('starterPct') or 0.0); expected_min=max(5.0,min(90.0,float(hist.get('avgMinutes') or 0.0))); starter=starter_pct>=50.0
        p['history']={'apps':hist.get('apps'),'starts':hist.get('starts'),'minutes':hist.get('minutes'),
                      'starterPct':starter_pct,'avgMinutes':hist.get('avgMinutes'),
                      'fouls90':hist.get('fouls90'),'fouled90':hist.get('fouled90'),
                      'shots90':hist.get('shots90'),'sot90':hist.get('sot90'),
                      'cards90':hist.get('cards90'),'goals90':round((hist.get('goals') or 0)/(hist.get('minutes') or 1)*90,2),
                      'assists90':round((hist.get('assists') or 0)/(hist.get('minutes') or 1)*90,2)}
        def prob_over(lam,line):
            return max(0.0,min(1.0,1-sum(pois(k,lam) for k in range(int(line)+1))))
        rates=[('Falli commessi',hist.get('fouls90') or 0),('Falli subiti',hist.get('fouled90') or 0),
               ('Tiri',hist.get('shots90') or 0),('Tiri in porta',hist.get('sot90') or 0),
               ('Cartellini',hist.get('cards90') or 0),('Gol',p['history']['goals90']),('Assist',p['history']['assists90'])]
        lines_by={'Falli commessi':(0.5,1.5,2.5),'Falli subiti':(0.5,1.5,2.5),
                  'Tiri':(0.5,1.5,2.5),'Tiri in porta':(0.5,1.5),
                  'Cartellini':(0.5,1.5),'Gol':(0.5,1.5),'Assist':(0.5,1.5)}
        props=[]
        for label,rate in rates:
            lam=max(0.01,rate*expected_min/90)
            for line in lines_by[label]:
                pr=prob_over(lam,line)
                props.append({'market':f'{label} O{line}','prob':round(pr*100,1),'lambda':round(lam,2)})
        p['expectedMinutes']=round(expected_min)
        p['starterProbability']=round(starter_pct,1)
        p['propCandidates']=sorted(props,key=lambda x:x['prob'],reverse=True)
        p['foulProbability']=next((x['prob'] for x in props if x['market']=='Falli commessi O0.5'),None)
        p['cardProbability']=next((x['prob'] for x in props if x['market']=='Cartellini O0.5'),None)
        p['dataBasis']=(f"Fantacalcio.it · {hist.get('apps')} gare · {hist.get('starts',0)} da titolare · {hist.get('minutes')} minuti storici" if p.get('fromProbableSource') else f"{hist.get('apps')} gare · {hist.get('starts',0)} da titolare · {hist.get('minutes')} minuti storici")
        result['players'].append(p)

    result['available']=bool(e or result['players'])
    result['players']=sorted(result['players'],key=lambda x:(x['team'],not bool(x.get('substitute')), -float(x.get('starterProbability') or 0),-(x.get('history',{}).get('minutes') or 0)))
    if candidates and not lu:
        result['notes'].append('Probabili formazioni e percentuali di titolarità da Fantacalcio.it; non sono formazioni ufficiali.'+(f' Ultimo aggiornamento fonte: {probable_updated}.' if probable_updated else ''))
    elif not lu: result['notes'].append('Formazioni ufficiali non ancora disponibili: le stime migliorano quando la formazione è confermata.')
    result['notes'].append('Le probabilità sono stime Poisson basate su tassi storici e minuti attesi; non sono garanzie e non vengono inventati dati.')
    return result

def news():
    q=quote_plus('Serie A calcio Italia')
    try:
        raw=get('https://news.google.com/rss/search?q='+q+'&hl=it&gl=IT&ceid=IT:it');root=ET.fromstring(raw);items=[]
        for it in root.findall('.//item')[:10]:items.append({'title':it.findtext('title') or '','link':it.findtext('link') or '','date':it.findtext('pubDate') or '','source':it.findtext('source') or ''})
        return items
    except:return []

@app.route('/')
def home():return render_template('index.html')
@app.get('/api/status')
def api_status():
    d=load();return jsonify(ok=True,data={'updated':d.get('updated'),'played':len(current(d)),'upcoming':len(upcoming(d)),'teams':len(teams(d)),'schedule':len(d.get('schedule',[])),'errors':d.get('errors',[]),'validation':d.get('validation',{}),'updater':d.get('updater',{}),'refreshing':_refresh_running})
@app.post('/api/refresh')
def api_refresh():
    try:
        started=_start_background_refresh(force_stats=False)
        d=load()
        return jsonify(ok=True,data={'status':'started' if started else 'already_running','updated':d.get('updated'),'played':len(current(d)),'upcoming':len(upcoming(d)),'teams':len(teams(d)),'schedule':len(d.get('schedule',[])),'errors':d.get('errors',[]),'refreshing':_refresh_running})
    except Exception as e:return jsonify(ok=False,error=str(e)),500
@app.get('/api/matches')
def api_matches():
    # Lightweight match index for the Player Analyzer. Do NOT run model_obj()
    # for every upcoming match during startup.
    d=load();mp={(norm_team(r['home']),norm_team(r['away'])):r['round'] for r in d['schedule']}
    out=[]
    for r in upcoming(d):
        rr=dict(r);rr['round']=mp.get((norm_team(r['home']),norm_team(r['away'])),r.get('round'));out.append(rr)
    return jsonify(ok=True,matches=out)

@app.get('/api/rounds')
def api_rounds():
    # Lightweight calendar endpoint. Modeling is performed only for the
    # selected round through /api/round/<n>.
    d=load();pk={(norm_team(r['home']),norm_team(r['away'])) for r in current(d)};groups={}
    today=date.today().isoformat()
    for r in d['schedule']:
        key=(norm_team(r['home']),norm_team(r['away']))
        status='played' if key in pk else ('upcoming' if r['date']>=today else 'past')
        groups.setdefault(r['round'],[]).append({'date':r['date'],'time':r.get('time',''),'home':r['home'],'away':r['away'],'round':r['round'],'status':status})
    rows=[]
    for n,ms in sorted(groups.items()):
        rows.append({'round':n,'status':'upcoming' if any(x['status']=='upcoming' for x in ms) else 'played' if all(x['status']=='played' for x in ms) else 'past','matches':ms})
    return jsonify(ok=True,rounds=rows)

@app.get('/api/round/<int:n>')
def api_round(n):
    d=load()
    ms=[r for r in d['schedule'] if int(r.get('round',0))==int(n)]
    out=[]
    for r in ms:
        out.append(model_obj(d,r))
    return jsonify(ok=True,round=n,matches=out)
@app.get('/api/match')
def api_match():
    d=load();h=request.args.get('home');a=request.args.get('away');dt=request.args.get('date');r=next((x for x in d['schedule'] if x['home']==h and x['away']==a and x['date']==dt),None)
    if not r:return jsonify(ok=False,error='Partita non trovata'),404
    obj=model_obj(d,r);hp=team_profile(d,h);ap=team_profile(d,a)
    obj['explanation']={'formaCasa':hp['form'],'formaTrasferta':ap['form'],'homeGF':hp['home_gf'],'homeGA':hp['home_ga'],'awayGF':ap['away_gf'],'awayGA':ap['away_ga'],'dataQuality':obj.get('data_quality')}
    obj['playerProps']=player_props(d,r)
    return jsonify(ok=True,match=obj)
@app.get('/api/player-props')
def api_player_props():
    d=load();h=request.args.get('home');a=request.args.get('away');dt=request.args.get('date')
    # Match by exact fixture first. If the local calendar has a provisional date,
    # fall back to the same home/away pair and let sofa_event_for reconcile the date.
    r=next((x for x in d['schedule'] if x['home']==h and x['away']==a and x['date']==dt),None)
    if not r:
        candidates=[x for x in d['schedule'] if x['home']==h and x['away']==a]
        if candidates:
            try:
                target=date.fromisoformat(dt) if dt else date.today()
                r=min(candidates,key=lambda x:abs((date.fromisoformat(x['date'])-target).days))
            except Exception:
                r=candidates[0]
    if not r:return jsonify(ok=False,error='Partita non trovata'),404
    return jsonify(ok=True,data=player_props(d,r))
@app.get('/api/news')
def api_news():return jsonify(ok=True,items=news())

@app.get('/api/match-context')
def api_match_context():
    d=load();h=request.args.get('home');a=request.args.get('away');dt=request.args.get('date');r=next((x for x in d['schedule'] if x['home']==h and x['away']==a and x['date']==dt),None)
    if not r:return jsonify(ok=False,error='Partita non trovata'),404
    return jsonify(ok=True,context=availability_context(d,r),news={'home':team_news(h),'away':team_news(a)})

@app.get('/api/news/team/<path:t>')
def api_team_news(t):return jsonify(ok=True,team=t,items=team_news(t,12))
@app.get('/api/teams')
def api_teams():return jsonify(ok=True,teams=teams(load()))
@app.get('/api/team/<path:t>')
def api_team(t):
    d=load()
    n=max(1,min(int(request.args.get('n',10)),15))
    venue=request.args.get('venue','all')
    if venue not in ('all','home','away'): venue='all'
    rs=sorted([r for r in played(d) if t in (r['home'],r['away']) and (venue=='all' or (venue=='home' and r['home']==t) or (venue=='away' and r['away']==t))],key=lambda x:x['date'])[-n:]
    rows=[]
    for r in rs:
        is_home=(r['home']==t)
        rows.append({
            **r,
            'team_side':'home' if is_home else 'away',
            'team_shots': r.get('hs') if is_home else r.get('as'),
            'opponent_shots': r.get('as') if is_home else r.get('hs'),
            'team_sot': r.get('hst') if is_home else r.get('ast'),
            'opponent_sot': r.get('ast') if is_home else r.get('hst'),
            'team_corners': r.get('hc') if is_home else r.get('ac'),
            'opponent_corners': r.get('ac') if is_home else r.get('hc'),
            'team_xg': (r.get('xgh') if is_home else r.get('xga')) if (r.get('xgh') is not None and r.get('xga') is not None) else estimate_xg_from_shots(r.get('hs') if is_home else r.get('as'), r.get('hst') if is_home else r.get('ast')),
            'opponent_xg': (r.get('xga') if is_home else r.get('xgh')) if (r.get('xgh') is not None and r.get('xga') is not None) else estimate_xg_from_shots(r.get('as') if is_home else r.get('hs'), r.get('ast') if is_home else r.get('hst')),
            'team_xg_source': 'SofaScore' if r.get('xgh') is not None and r.get('xga') is not None else 'Stima da tiri/porta',
            'team_fouls': r.get('hf') if is_home else r.get('af'),
            'opponent_fouls': r.get('af') if is_home else r.get('hf'),
            'team_yellow': r.get('hy') if is_home else r.get('ay'),
            'opponent_yellow': r.get('ay') if is_home else r.get('hy'),
            'stats_source': r.get('stats_source') or ('Football-Data' if stats_verified(r) else None),
            'data_quality': r.get('data_quality',{}),
        })
    return jsonify(ok=True,team=t,venue=venue,profile=team_profile(d,t,n,venue),matches=rows)
@app.get('/api/odds-status')
def api_odds_status():
    key_configured=bool(API_FOOTBALL_KEY)
    cache=_odds_cache_load()
    sample=[]
    d=load()
    for r in d.get('schedule',[]):
        if r.get('date') and r.get('home') and r.get('away'):
            sample.append(r);
            if len(sample)>=1: break
    probe=None
    if sample:
        probe_r=sample[0]
        probe=odds_for(probe_r)
    return jsonify(ok=True,configured=key_configured,bookmaker=(probe.get('_bookmaker') if probe else None),odds={k:v for k,v in (probe or {}).items() if k!='_bookmaker'},last_error=API_FOOTBALL_LAST_ERROR,last_status=API_FOOTBALL_LAST_STATUS,cache_entries=len(cache),note='La chiave non viene mai restituita.')

@app.get('/api/validation')
def api_validation():
    d=load(); rows=[]
    for r in current(d):
        if r.get('data_quality',{}).get('stats')=='verified':
            rows.append({'date':r['date'],'home':r['home'],'away':r['away'],'shots_home':r.get('hs'),'shots_away':r.get('as'),'sot_home':r.get('hst'),'sot_away':r.get('ast'),'corners_home':r.get('hc'),'corners_away':r.get('ac'),'source':r.get('stats_source'),'event_id':r.get('sofa_event_id')})
    return jsonify(ok=True,validation=d.get('validation',{}),matches=rows)
@app.get('/api/backtest')
def api_backtest():
    d=load();rs=sorted(played(d),key=lambda x:x['date']);rows=[];brier=[]
    # Lightweight rolling validation: only evaluate after each team has at least 3 prior matches.
    for r in rs:
        if r['season']=='2026/27':continue
        hist={'seasons':{'2026/27':[x for x in rs if x['date']<r['date']]},'schedule':[],'fixtures':[]}
        if len([x for x in hist['seasons']['2026/27'] if r['home'] in (x['home'],x['away'])])<3:continue
        p=markets(*xg(hist,r['home'],r['away']));actual='1' if r['hg']>r['ag'] else 'X' if r['hg']==r['ag'] else '2';loss=sum((p[k]-(1 if k==actual else 0))**2 for k in ('1','X','2'))/3;brier.append(loss)
    return jsonify(ok=True,metrics={'matches':len(brier),'brier1X2':round(sum(brier)/len(brier),4) if brier else None,'note':'Backtest walk-forward semplificato; le partite future non entrano nel training.'})

if __name__=='__main__':app.run(host='127.0.0.1',port=8787)