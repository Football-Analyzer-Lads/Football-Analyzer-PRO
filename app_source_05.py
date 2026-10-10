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
        p=item.get('player',{});s=item.get('statistics') or {}
        mins=s.get('minutesPlayed') or s.get('minutes') or 0
        if not p.get('name'):continue
        def first_value(*keys):
            for key in keys:
                if s.get(key) is not None:return s.get(key)
            return None
        rows.append({'id':p.get('id'),'name':p.get('name'),'position':p.get('position'),
            'substitute':item.get('substitute',False),'minutes':mins,
            'fouls':first_value('fouls','totalFouls'),
            'fouled':first_value('wasFouled','fouled','foulsSuffered'),
            'shots':first_value('totalShots','totalScoringAtt','shots'),
            'sot':first_value('onTargetScoringAttempt','shotsOnTarget','shotsOnGoal'),
            'cards':first_value('yellowCards','yellowCard',) or 0,
            'goals':first_value('goals','goal') or 0,
            'assists':first_value('assists','goalAssist') or 0})
    return rows

def _player_name_key(value):
    import unicodedata
    value=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+',' ',value).strip()

def _stat_float(value):
    if value is None or value=='':return 0.0
    try:return float(value)
    except Exception:return 0.0

def player_history(team_id):
    # Use actual per-player statistics from recent finished matches. Initialize
    # aggregate counters at zero to avoid double-counting the first appearance.
    agg={};pages=[]
    for page in (0,1):
        data=sofa_get(f'/team/{team_id}/events/last/{page}',ttl=1800)
        evs=(data or {}).get('events',[])
        if not evs:break
        pages.extend(evs)
        if len(pages)>=24:break
    for e in pages[:24]:
        if e.get('status',{}).get('type')!='finished':continue
        lu=sofa_get(f"/event/{e['id']}/lineups",ttl=7*86400)
        if not lu:continue
        side='home' if e.get('homeTeam',{}).get('id')==team_id else 'away'
        for s in player_stats_from_lineup(lu,side):
            pid=s.get('id')
            mins=_stat_float(s.get('minutes'))
            if pid is None or mins<=0:continue
            if pid not in agg:
                agg[pid]={'id':pid,'name':s.get('name'),'position':s.get('position'),
                          'apps':0,'starts':0,'minutes':0.0,'fouls':0.0,'fouled':0.0,
                          'shots':0.0,'sot':0.0,'cards':0.0,'goals':0.0,'assists':0.0}
            a=agg[pid];a['apps']+=1
            if not s.get('substitute'):a['starts']+=1
            for k in ('minutes','fouls','fouled','shots','sot','cards','goals','assists'):
                if s.get(k) is not None:a[k]+=_stat_float(s.get(k))
    out=[]
    for a in agg.values():
        mins=a['minutes'] or 1.0
        a['fouls90']=round(a['fouls']/mins*90,2);a['fouled90']=round(a['fouled']/mins*90,2)
        a['shots90']=round(a['shots']/mins*90,2);a['sot90']=round(a['sot']/mins*90,2)
        a['cards90']=round(a['cards']/mins*90,2)
        a['starterPct']=round(100*a['starts']/max(1,a['apps']),1)
        a['avgMinutes']=round(a['minutes']/max(1,a['apps']),1)
        out.append(a)
    return sorted(out,key=lambda x:x['minutes'],reverse=True)

def api_football_player_history(team_name):
    """Fetch season totals from API-Football and combine current + previous Serie A season.
    Rows with fewer than 120 minutes are retained so early-season/squad players are not
    silently omitted; the UI labels small samples transparently.
    """
    try:
        if not API_FOOTBALL_KEY:return []
        target=norm_team(team_name).lower()
        combined={}
        for season in (2026,2025):
            team_data=api_football_get('/teams?name='+quote_plus(str(team_name))+'&league='+str(API_FOOTBALL_LEAGUE)+'&season='+str(season),ttl=24*3600) or {}
            team_rows=team_data.get('response') or []
            team_obj=None
            for item in team_rows:
                t=item.get('team') or {}
                if norm_team(t.get('name','')).lower()==target:
                    team_obj=t;break
            if not team_obj and len(team_rows)==1:
                team_obj=(team_rows[0].get('team') or {})
            tid=(team_obj or {}).get('id')
            if not tid:continue
            page=1
            while page<=10:
                data=api_football_get(f'/players?league={API_FOOTBALL_LEAGUE}&season={season}&team={tid}&page={page}',ttl=6*3600) or {}
                rows=data.get('response') or []
                if not rows:break
                for row in rows:
                    p=row.get('player') or {}
                    st=(row.get('statistics') or [{}])[0]
                    g=st.get('games') or {}
                    mins=_stat_float(g.get('minutes'))
                    apps=int(_stat_float(g.get('appearences')))
                    starts=int(_stat_float(g.get('lineups')))
                    if not p.get('id') or mins<=0:continue
                    shots=st.get('shots') or {};fouls=st.get('fouls') or {}
                    cards=st.get('cards') or {};goals=st.get('goals') or {}
                    key=_player_name_key(p.get('name')) or str(p.get('id'))
                    if key not in combined:
                        combined[key]={'id':p.get('id'),'name':p.get('name'),'position':g.get('position'),
                            'apps':0,'starts':0,'minutes':0.0,'fouls':0.0,'fouled':0.0,
                            'shots':0.0,'sot':0.0,'cards':0.0,'goals':0.0,'assists':0.0,'historySeasons':[]}
                    a=combined[key]
                    # If a player has two season rows, aggregate genuine totals before
                    # deriving per-90 rates; never add provider IDs across namespaces.
                    a['apps']+=apps;a['starts']+=starts;a['minutes']+=mins
                    a['fouls']+=_stat_float(fouls.get('committed'))
                    a['fouled']+=_stat_float(fouls.get('drawn'))
                    a['shots']+=_stat_float(shots.get('total'));a['sot']+=_stat_float(shots.get('on'))
                    a['cards']+=_stat_float(cards.get('yellow'))
                    a['goals']+=_stat_float(goals.get('total'));a['assists']+=_stat_float(goals.get('assists'))
                    if season not in a['historySeasons']:a['historySeasons'].append(season)
                if len(rows)<20:break
                page+=1
        out=[]
        for a in combined.values():
            mins=a['minutes'] or 1.0
            a['starterPct']=round(100*a['starts']/max(1,a['apps']),1)
            a['avgMinutes']=round(a['minutes']/max(1,a['apps']),1)
            a['fouls90']=round(a['fouls']/mins*90,2);a['fouled90']=round(a['fouled']/mins*90,2)
            a['shots90']=round(a['shots']/mins*90,2);a['sot90']=round(a['sot']/mins*90,2)
            a['cards90']=round(a['cards']/mins*90,2)
            out.append(a)
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

def api_football_live_match_data(r):
    """Fetch live team and player box-score for one selected Serie A fixture.
    Uses API-Football's authenticated endpoints; cached to conserve daily quota.
    """
    if not API_FOOTBALL_KEY:
        return {'available':False,'reason':'API_FOOTBALL_KEY non configurata'}
    try:
        today=date.today().isoformat()
        if r.get('date') != today:
            return {'available':False,'reason':'La partita selezionata non è in data odierna'}
        payload=api_football_get(f'/fixtures?live={API_FOOTBALL_LEAGUE}',ttl=90) or {}
        live_fixtures=payload.get('response') or []
        def team_key(value):
            s=norm_team(str(value or '')).lower()
            s=re.sub(r'\b(fc|cf|ssc|calcio|(?:19|20)\d{2})\b','',s)
            return re.sub(r'[^a-z0-9]+','',s)
        def same_club(a,b):
            return bool(a and b) and (a==b or (min(len(a),len(b))>=4 and (a.endswith(b) or b.endswith(a))))
        target_home=team_key(r.get('home'));target_away=team_key(r.get('away'))
        match=None
        for fx in live_fixtures:
            teams=fx.get('teams') or {}
            hh=team_key((teams.get('home') or {}).get('name'))
            aa=team_key((teams.get('away') or {}).get('name'))
            if same_club(hh,target_home) and same_club(aa,target_away):
                match=fx;break
        if not match:
            return {'available':True,'isLive':False,'reason':'Nessuna partita selezionata attualmente live su API-Football'}
        fixture=(match.get('fixture') or {})
        fixture_id=fixture.get('id')
        if not fixture_id:
            return {'available':False,'reason':'ID fixture live non disponibile'}
        status=fixture.get('status') or {}
        score=match.get('goals') or {}
        team_box=api_football_get(f'/fixtures/statistics?fixture={fixture_id}',ttl=120) or {}
        player_box=api_football_get(f'/fixtures/players?fixture={fixture_id}',ttl=120) or {}
        side_ids={}
        for side in ('home','away'):
            side_ids[side]=((match.get('teams') or {}).get(side) or {}).get('id')
        team_stats={'home':[],'away':[]}
        raw_team_stats=team_box.get('response') or []
        for item in raw_team_stats:
            team=item.get('team') or {}
            side='home' if team.get('id')==side_ids['home'] else 'away' if team.get('id')==side_ids['away'] else None
            if not side:continue
            for stat in item.get('statistics') or []:
                label=str(stat.get('type') or '').strip()
                val=stat.get('value')
                if val is not None:
                    team_stats[side].append({'label':label,'value':val})
        players=[]
        for team_item in (player_box.get('response') or []):
            team=team_item.get('team') or {}
            side='home' if team.get('id')==side_ids['home'] else 'away' if team.get('id')==side_ids['away'] else None
            if not side:continue
            for item in team_item.get('players') or []:
                p=item.get('player') or {}
                stat_list=item.get('statistics') or []
                st=stat_list[0] if stat_list else {}
                games=st.get('games') or {};shots=st.get('shots') or {};fouls=st.get('fouls') or {}
                cards=st.get('cards') or {};goals=st.get('goals') or {}
                if not p.get('name'):continue
                players.append({
                    'name':p.get('name'),'team':team.get('name') or r[side],'side':side,
                    'minutes':games.get('minutes'),'rating':games.get('rating'),
                    'shots':shots.get('total'),'sot':shots.get('on'),
                    'fouls':fouls.get('committed'),'fouled':fouls.get('drawn'),
                    'yellow':cards.get('yellow'),'red':cards.get('red'),
                    'goals':goals.get('total'),'assists':goals.get('assists')
                })
        return {
            'available':True,'isLive':True,'source':'API-Football',
            'fixtureId':fixture_id,'status':status.get('long') or status.get('short') or 'Live',
            'elapsed':status.get('elapsed'),'home':(match.get('teams') or {}).get('home',{}).get('name') or r['home'],
            'away':(match.get('teams') or {}).get('away',{}).get('name') or r['away'],
            'homeGoals':score.get('home'),'awayGoals':score.get('away'),
            'teamStats':team_stats,'players':players,
            'updated':datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as exc:
        return {'available':False,'reason':'Errore recupero dati live: '+str(exc)[:180]}

# ---- PitchAPI free Serie A player-data integration -----------------------------
def pitchapi_get(path,ttl=3600,force=False):
    """Read a PitchAPI endpoint. Cache only successful JSON responses."""
    global PITCHAPI_LAST_ERROR,PITCHAPI_LAST_STATUS
    if not PITCHAPI_API_KEY:
        PITCHAPI_LAST_ERROR='PITCHAPI_API_KEY non configurata'
        PITCHAPI_LAST_STATUS={'configured':False,'ok':False,'reason':PITCHAPI_LAST_ERROR,'path':path}
        return None
    cache=_context_cache_load();key='pitchapi:v1:'+path;now=time.time();v=cache.get(key)
    if not force and v and now-v.get('ts',0)<ttl:
        PITCHAPI_LAST_ERROR=''
        PITCHAPI_LAST_STATUS={'configured':True,'ok':True,'cached':True,'path':path,'http':200}
        return v.get('data')
    try:
        req=Request(PITCHAPI_BASE+path,headers={'X-API-KEY':PITCHAPI_API_KEY,
                    'Accept':'application/json','User-Agent':'FootballAnalyzer-PRO/6.2'})
        with urlopen(req,timeout=25) as resp:
            payload=json.loads(resp.read().decode('utf-8'))
            code=getattr(resp,'status',200)
        if not isinstance(payload,dict) or payload.get('error'):
            err=(payload.get('error') if isinstance(payload,dict) else None) or {'message':'Risposta JSON non valida'}
            PITCHAPI_LAST_ERROR=str(err)[:350]
            PITCHAPI_LAST_STATUS={'configured':True,'ok':False,'path':path,'http':code,'error':err}
            return None
        if 'data' not in payload:
            PITCHAPI_LAST_ERROR='Risposta PitchAPI senza campo data'
            PITCHAPI_LAST_STATUS={'configured':True,'ok':False,'path':path,'http':code,'error':PITCHAPI_LAST_ERROR}
            return None
        data=payload.get('data')
        cache[key]={'ts':now,'data':data}
        _context_cache_save(cache)
        PITCHAPI_LAST_ERROR=''
        PITCHAPI_LAST_STATUS={'configured':True,'ok':True,'cached':False,'path':path,'http':code}
        return data
    except Exception as exc:
        PITCHAPI_LAST_ERROR=f'{type(exc).__name__}: {exc}'
        PITCHAPI_LAST_STATUS={'configured':True,'ok':False,'path':path,'http':getattr(exc,'code',None),'error':PITCHAPI_LAST_ERROR}
        return None

def pitchapi_serie_a():
    """Resolve Serie A's opaque PitchAPI league ID and current season dynamically."""
    leagues_data=pitchapi_get('/leagues',ttl=7*86400)
    leagues=(leagues_data or {}).get('leagues',[]) if isinstance(leagues_data,dict) else []
    league=next((x for x in leagues if str(x.get('name','')).strip().lower()=='serie a'
                 and str(x.get('country_code','')).upper() in ('ITA','IT','ITALY')),None)
    if not league:
        league=next((x for x in leagues if str(x.get('name','')).strip().lower()=='serie a'),None)
    if not league or not league.get('id'):
        if PITCHAPI_API_KEY and PITCHAPI_LAST_STATUS.get('ok'):
            PITCHAPI_LAST_STATUS.update({'ok':False,'error':'Serie A non trovata in /v1/leagues'})
        return None
    detail=pitchapi_get('/leagues/'+str(league['id']),ttl=7*86400)
    season=(detail or {}).get('season') if isinstance(detail,dict) else None
    seasons=league.get('seasons') or []
    if not season and seasons:
        season=seasons[0]
    if not season:
        y=date.today().year
        season=f'{y}/{y+1}' if date.today().month>=7 else f'{y-1}/{y}'
    try:
        start=int(str(season).split('/')[0])
        previous=f'{start-1}/{start}'
    except Exception:
        y=date.today().year;previous=f'{y-1}/{y}'
    return {'id':league['id'],'name':league.get('name','Serie A'),'season':season,
            'seasons':list(dict.fromkeys([season,previous]+[x for x in seasons if x!=season]))}

def pitchapi_league_matches(league_id,season,status='played'):
    # The documented endpoint accepts season, not a status query parameter.
    # Fetch the supported response once and filter the status locally.
    ttl=90 if status=='all' else 6*3600
    path=f'/leagues/{league_id}/matches?season={quote_plus(str(season))}'
    data=pitchapi_get(path,ttl=ttl)
    matches=data.get('matches',[]) if isinstance(data,dict) else []
    def state(match):
        return re.sub(r'[^a-z0-9]+','',str(match.get('status') or '').lower())
    finished={'finished','fulltime','afterextratime','penaltyshootout','aet','ft'}
    pending={'scheduled','notstarted','upcoming','tbd','notplayed'}
    if status=='played':return [m for m in matches if state(m) in finished]
    if status=='upcoming':return [m for m in matches if state(m) in pending]
    if status=='live':return [m for m in matches if _pitchapi_live_status(m.get('status'))]
    return matches

def _pitchapi_team_key(name):
    s=_player_name_key(norm_team(str(name or '')))
    for token in ('football club','calcio','inter milan','ac milan','as roma','ssc napoli'):
        if token in ('inter milan','ac milan','as roma','ssc napoli'):
            continue
        s=s.replace(token,' ')
    return re.sub(r'[^a-z0-9]+','',s)

def _pitchapi_same_team(a,b):
    x=_pitchapi_team_key(a);y=_pitchapi_team_key(b)
    if not x or not y:return False
    if x==y:return True
    return min(len(x),len(y))>=4 and (x.endswith(y) or y.endswith(x) or x in y or y in x)

def pitchapi_matches_for_fixture(r,status='all'):
    league=pitchapi_serie_a()
    if not league:return (None,[])
    candidates=[]
    target_date=str(r.get('date') or '')
    for season in league['seasons'][:2]:
        rows=pitchapi_league_matches(league['id'],season,status=status)
        for m in rows:
            home=(m.get('home_team') or {}).get('name','')
            away=(m.get('away_team') or {}).get('name','')
            if not (_pitchapi_same_team(home,r.get('home')) and _pitchapi_same_team(away,r.get('away'))):continue
            md=str(m.get('date') or '')
            try:distance=abs((date.fromisoformat(md)-date.fromisoformat(target_date)).days)
            except Exception:distance=0
            candidates.append((distance,m))
    if not candidates:return (league,[])
    candidates.sort(key=lambda x:(x[0],x[1].get('date','')))
    # An exact/near fixture is preferred; still return a unique same-team match
    # if the local calendar is provisional and provider dates were rescheduled.
    return league,[candidates[0][1]]

def _pitchapi_flat_player_stats(player_row):
    """Flatten the documented PitchAPI stat groups by stable inner stat key."""
    out={};labels={}
    for group in (player_row.get('stats') or []):
        for label,item in (group.get('stats') or {}).items():
            if not isinstance(item,dict):continue
            spec=item.get('stat') or {}
            key=spec.get('key') or item.get('key')
            value=spec.get('value')
            if key and value is not None:out[str(key).lower()]=value
            norm=re.sub(r'[^a-z0-9]+','_',str(label).lower()).strip('_')
            if norm and value is not None:labels[norm]=value
            if key and spec.get('total') is not None:out[str(key).lower()+'_total']=spec.get('total')
    out['_labels']=labels
    return out

def _pitchapi_pick(stats,keys,labels=()):
    for key in keys:
        if key in stats and stats[key] is not None:return stats[key]
    label_map=stats.get('_labels') or {}
    for label in labels:
        key=re.sub(r'[^a-z0-9]+','_',label.lower()).strip('_')
        if key in label_map and label_map[key] is not None:return label_map[key]
    return None

def _pitchapi_num(value):
    try:
        if value is None or value=='':return None
        return float(value)
    except Exception:return None

def _pitchapi_live_status(status):
    # Deliberately conservative: never show a finished or unknown-status fixture
    # as live just because its provider status is new/unrecognised.
    s=re.sub(r'[^a-z0-9]+','',str(status or '').lower())
    return s in ('live','inplay','inprogress','firsthalf','secondhalf','halftime','half',
                 '1h','2h','ht','extratime','extratimebreak','penalties','penaltyshootoutlive',
                 'break','suspendedlive')

def pitchapi_live_match_data(r):
    """Load one selected Serie A match's live team and individual statistics."""
    if not PITCHAPI_API_KEY:
        return {'available':False,'isLive':False,'reason':'PITCHAPI_API_KEY non configurata'}
    if str(r.get('date') or '')!=date.today().isoformat():
        return {'available':False,'isLive':False,'reason':'Partita selezionata non in data odierna'}
    # The date endpoint returns the free-tier covered fixtures for today and
    # avoids scanning whole seasons to find a live match.
    day_data=pitchapi_get('/date/'+date.today().isoformat(),ttl=25)
    day_matches=day_data.get('matches',[]) if isinstance(day_data,dict) else []
    target_home=r.get('home');target_away=r.get('away')
    matches=[m for m in day_matches
             if _pitchapi_same_team((m.get('home_team') or {}).get('name',''),target_home)
             and _pitchapi_same_team((m.get('away_team') or {}).get('name',''),target_away)]
    if not matches:
        return {'available':False,'isLive':False,'reason':str(PITCHAPI_LAST_ERROR or 'Partita non trovata nel calendario PitchAPI per oggi')}
    m=matches[0];mid=m.get('id')
    if not mid:return {'available':False,'isLive':False,'reason':'ID partita PitchAPI mancante'}
    summary=pitchapi_get('/matches/'+str(mid),ttl=35)
    summary=summary if isinstance(summary,dict) else m
    status=summary.get('status') or m.get('status') or ''
    if not _pitchapi_live_status(status):
        return {'available':True,'isLive':False,'source':'PitchAPI','reason':'Partita non live (stato: '+str(status or 'non indicato')+')'}
    detail_players=pitchapi_get('/matches/'+str(mid)+'/players',ttl=50)
    player_rows=detail_players if isinstance(detail_players,list) else []
    home=(summary.get('home_team') or m.get('home_team') or {})
    away=(summary.get('away_team') or m.get('away_team') or {})
    home_id=home.get('id');away_id=away.get('id')
    players=[]
    for row in player_rows:
        p=row.get('player') or {};tm=row.get('team_id')
        side='home' if tm==home_id else 'away' if tm==away_id else None
        if not side:continue
        st=_pitchapi_flat_player_stats(row)
        minutes=_pitchapi_pick(st,('minutes_played','minutes'))
        total_shots=_pitchapi_pick(st,('total_shots','shots','total_scoring_att'),('total shots','shots'))
        sot=_pitchapi_pick(st,('shots_on_target','on_target_shots','shot_accuracy','on_target_scoring_att'),('shot accuracy','shots on target'))
        players.append({'name':p.get('name'),'team':home.get('name') if side=='home' else away.get('name'),'side':side,
            'minutes':minutes,'rating':_pitchapi_pick(st,('rating_title','rating'),('rating',)),
            'shots':total_shots,'sot':sot,
            'fouls':_pitchapi_pick(st,('fouls_committed','fouls'),('fouls committed','fouls')),
            'fouled':_pitchapi_pick(st,('fouls_won','fouls_drawn','foul_won','foul_drawn'),('fouls won','fouls drawn')),
            'yellow':_pitchapi_pick(st,('yellow_cards','yellow_card','yellowcard'),('yellow cards','yellow card')),
            'red':_pitchapi_pick(st,('red_cards','red_card','redcard'),('red cards','red card')),
            'goals':_pitchapi_pick(st,('goals',),('goals',)),'assists':_pitchapi_pick(st,('assists',),('assists',))})
    team_data=pitchapi_get('/matches/'+str(mid)+'/stats',ttl=50)
    periods=(team_data or {}).get('periods',[]) if isinstance(team_data,dict) else []
    period=next((x for x in periods if str(x.get('period','')).lower() in ('all','fullmatch')),periods[0] if periods else {})
    team_stats={'home':[],'away':[]}
    for group in (period or {}).get('groups',[]):
        for item in group.get('items',[]):
            label=item.get('title') or item.get('key')
            hv=item.get('home');av=item.get('away')
            if label and hv is not None:team_stats['home'].append({'label':str(label),'value':hv})
            if label and av is not None:team_stats['away'].append({'label':str(label),'value':av})
    return {'available':True,'isLive':True,'source':'PitchAPI','fixtureId':mid,'status':status,
            'elapsed':summary.get('minute') or summary.get('elapsed'),
            'home':home.get('name') or r.get('home'),'away':away.get('name') or r.get('away'),
            'homeGoals':summary.get('score_home'),'awayGoals':summary.get('score_away'),
            'teamStats':team_stats,'players':players,
            'updated':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

def pitchapi_player_history(team_name,target_date=None,limit=12):
    """Aggregate player performance from the last 12 completed Serie A matches for this club."""
    if not PITCHAPI_API_KEY:return []
    target_date=str(target_date or date.today().isoformat())
    team_key=_pitchapi_team_key(team_name)
    cache=_context_cache_load();cache_key='pitchapi_player_history:'+team_key+':'+target_date
    now=time.time();cached=cache.get(cache_key)
    if cached and isinstance(cached.get('data'),list):
        cached_rows=cached.get('data') or []
        cached_ttl=6*3600 if cached_rows else 300
        if now-cached.get('ts',0)<cached_ttl:
            PITCHAPI_LAST_STATUS={'configured':True,'ok':bool(cached_rows),'cached_history':True,
                'team':team_name,'players':len(cached_rows),
                'error':None if cached_rows else 'Nessun dato giocatore restituito da PitchAPI nelle ultime 5 minuti'}
            if not cached_rows:PITCHAPI_LAST_ERROR=PITCHAPI_LAST_STATUS['error']
            else:PITCHAPI_LAST_ERROR=''
            return cached_rows
    league=pitchapi_serie_a()
    if not league:return []
    matches_by_id={}
    for season in league['seasons'][:2]:
        for m in pitchapi_league_matches(league['id'],season,status='played'):
            mid=m.get('id')
            if not mid:continue
            md=str(m.get('date') or '')
            if target_date and md and md>=target_date:continue
            h=(m.get('home_team') or {}).get('name','');a=(m.get('away_team') or {}).get('name','')
            if _pitchapi_same_team(h,team_name) or _pitchapi_same_team(a,team_name):
                # Prefer the record with scores/status populated if two season feeds overlap.
                matches_by_id[mid]=m
    recent=sorted(matches_by_id.values(),key=lambda x:(str(x.get('date') or ''),str(x.get('time_utc') or '')),reverse=True)[:limit]
    agg={}
    errors=[]
    for match in recent:
        mid=match.get('id')
        raw=pitchapi_get('/matches/'+str(mid)+'/players',ttl=30*86400)
        if not isinstance(raw,list):
            if PITCHAPI_LAST_ERROR:errors.append(str(PITCHAPI_LAST_ERROR)[:100])
            continue
        match_home=(match.get('home_team') or {}).get('name','')
        match_away=(match.get('away_team') or {}).get('name','')
        home_id=(match.get('home_team') or {}).get('id');away_id=(match.get('away_team') or {}).get('id')
        wanted_side='home' if _pitchapi_same_team(match_home,team_name) else 'away'
        wanted_id=home_id if wanted_side=='home' else away_id
        lineup=pitchapi_get('/matches/'+str(mid)+'/lineups',ttl=30*86400)
        started=set()
        if isinstance(lineup,dict):
            side_data=lineup.get(wanted_side) or {}
            for sp in side_data.get('starters') or []:
                if sp.get('player_id') is not None:started.add(str(sp.get('player_id')))
                if sp.get('name'):started.add('name:'+_player_name_key(sp.get('name')))
        # The provider also exposes canonical per-shot data and match events.
        # Use these as metric fallbacks only when the player-stat row omits a field.
        shot_data=pitchapi_get('/matches/'+str(mid)+'/shots',ttl=30*86400)
        shot_feed_available=isinstance(shot_data,dict) and isinstance(shot_data.get('periods'),list)
        shot_counts={};sot_counts={};shot_xg={}
        if shot_feed_available:
            for period in shot_data.get('periods') or []:
                for shot in period.get('shots') or []:
                    shot_player=shot.get('player') or {}
                    shot_team=shot.get('team_id')
                    if wanted_id is not None and shot_team!=wanted_id:continue
                    sid=str(shot_player.get('id') or '')
                    sname=_player_name_key(shot_player.get('name'))
                    keys=[('id',sid)] if sid else []
                    if sname:keys.append(('name',sname))
                    for kind,pk in keys:
                        shot_counts[(kind,pk)]=shot_counts.get((kind,pk),0)+1
                        if shot.get('is_on_target') is True:
                            sot_counts[(kind,pk)]=sot_counts.get((kind,pk),0)+1
                        xg_value=_pitchapi_num(shot.get('expected_goals'))
                        if xg_value is not None:shot_xg[(kind,pk)]=shot_xg.get((kind,pk),0.0)+xg_value
        event_data=pitchapi_get('/matches/'+str(mid)+'/events',ttl=30*86400)
        events_feed_available=isinstance(event_data,dict) and isinstance(event_data.get('events'),list)
        yellow_counts={}
        if events_feed_available:
            for event in event_data.get('events') or []:
                etype=re.sub(r'[^a-z0-9]+','',str(event.get('event_type') or '').lower())
                if etype!='yellowcard':continue
                if wanted_id is not None and event.get('team_id')!=wanted_id:continue
                player=event.get('player') or {}
                pid_event=str(player.get('id') or '')
                pname_event=_player_name_key(player.get('name'))
                if pid_event:yellow_counts[('id',pid_event)]=yellow_counts.get(('id',pid_event),0)+1
                if pname_event:yellow_counts[('name',pname_event)]=yellow_counts.get(('name',pname_event),0)+1
        for row in raw:
            if wanted_id is not None and row.get('team_id')!=wanted_id:continue
            p=row.get('player') or {}
            pname=str(p.get('name') or '').strip()
            if not pname:continue
            stats=_pitchapi_flat_player_stats(row)
            mins=_pitchapi_num(_pitchapi_pick(stats,('minutes_played','minutes'),('minutes played','minutes')))
            if mins is None or mins<=0:continue
            pid=str(p.get('id') or _player_name_key(pname))
            key=pid
            if key not in agg:
                agg[key]={'id':pid,'name':pname,'position':p.get('position_id'),'apps':0,'starts':0,
                          'minutes':0.0,'goals':0.0,'assists':0.0,'xg':0.0,'fouls':0.0,
                          'fouled':0.0,'shots':0.0,'sot':0.0,'cards':0.0,
                          '_metric_minutes':{},'_metric_seen':{},'_historyProvider':'PitchAPI','historyMatches':[]}
            a=agg[key];a['apps']+=1;a['minutes']+=mins
            if pid in started or ('name:'+_player_name_key(pname)) in started:a['starts']+=1
            metric_keys={
                'goals':(('goals',),('goals',)),
                'assists':(('assists',),('assists',)),
                'xg':(('expected_goals','xg'),('expected goals','xg')),
                'fouls':(('fouls_committed','fouls'),('fouls committed','fouls')),
                'fouled':(('fouls_won','fouls_drawn','foul_won','foul_drawn'),('fouls won','fouls drawn')),
                'shots':(('total_shots','shots','total_scoring_att'),('total shots','shots')),
                'sot':(('shots_on_target','on_target_shots','shot_accuracy','on_target_scoring_att'),('shots on target','shot accuracy')),
                'cards':(('yellow_cards','yellow_card','yellowcard'),('yellow cards','yellow card'))
            }
            for field,(keys,labels) in metric_keys.items():
                val=_pitchapi_num(_pitchapi_pick(stats,keys,labels))
                lookup_id=('id',pid);lookup_name=('name',_player_name_key(pname))
                if val is None:
                    if field=='shots' and shot_feed_available:
                        val=shot_counts.get(lookup_id,shot_counts.get(lookup_name,0))
                    elif field=='sot' and shot_feed_available:
                        val=sot_counts.get(lookup_id,sot_counts.get(lookup_name,0))
                    elif field=='xg' and shot_feed_available:
                        val=shot_xg.get(lookup_id,shot_xg.get(lookup_name,0.0))
                    elif field=='cards' and events_feed_available:
                        val=yellow_counts.get(lookup_id,yellow_counts.get(lookup_name,0))
                if val is None:continue
                a[field]+=val
                a['_metric_minutes'][field]=a['_metric_minutes'].get(field,0.0)+mins
                a['_metric_seen'][field]=a['_metric_seen'].get(field,0)+1
            a['historyMatches'].append({'date':match.get('date'),'matchId':mid})
    out=[]
    for a in agg.values():
        mins=a['minutes'] or 1.0
        a['starterPct']=round(100*a['starts']/max(1,a['apps']),1)
        a['avgMinutes']=round(a['minutes']/max(1,a['apps']),1)
        for field in ('goals','assists','xg','fouls','fouled','shots','sot','cards'):
            denom=a['_metric_minutes'].get(field,0.0)
            a[field+'90']=round(a[field]/denom*90,2) if denom>0 else None
            if not denom:a[field]=None
        a['historySeasons']=sorted(set(str(x.get('date',''))[:4] for x in a['historyMatches'] if x.get('date')))
        a.pop('_metric_minutes',None);a.pop('_metric_seen',None)
        out.append(a)
    cache[cache_key]={'ts':now,'data':out}
    _context_cache_save(cache)
    PITCHAPI_LAST_STATUS={'configured':True,'ok':bool(out),'team':team_name,'matches_used':len(recent),'players':len(out),
        'error':None if out else (errors[-1] if errors else PITCHAPI_LAST_ERROR or 'Nessuno storico giocatore restituito da PitchAPI')}
    return sorted(out,key=lambda x:_pitchapi_num(x.get('minutes')) or 0,reverse=True)

def player_props(d,r):
    e=sofa_event_for(r)
    probable=fantacalcio_probable_lineups()
    probable_updated=probable.get('updated')
    result={'available':False,'source':'Fantacalcio.it + PitchAPI + SofaScore + API-Football',
            'eventId':e.get('id') if e else None,
            'referee':(e or {}).get('referee',{}).get('name'),'players':[],'notes':[],'lineupsAvailable':False,
            'probableLineupsAvailable':False,'probableLineupsUpdated':probable_updated,'probableLineupsSource':probable.get('source')}
    lu=sofa_get(f"/event/{e['id']}/lineups",ttl=900) if e else None
    result['lineupsAvailable']=bool(lu)
    result['pitchAPIConfigured']=bool(PITCHAPI_API_KEY)
    result['pitchAPIStatus']={'configured':bool(PITCHAPI_API_KEY),'ok':None,'error':None}
    # Prefer PitchAPI live box score. Keep existing API-Football as a fallback.
    is_today=str(r.get('date') or '')==date.today().isoformat()
    if is_today and PITCHAPI_API_KEY:
        result['liveMatch']=pitchapi_live_match_data(r)
        result['pitchAPIStatus']={'configured':True,'ok':bool(PITCHAPI_LAST_STATUS.get('ok',result['liveMatch'].get('available'))),
                                  'error':PITCHAPI_LAST_ERROR or result['liveMatch'].get('reason')}
        if not result['liveMatch'].get('isLive') and API_FOOTBALL_KEY:
            alt_live=api_football_live_match_data(r)
            if alt_live.get('isLive'):result['liveMatch']=alt_live
    elif is_today:
        result['liveMatch']=api_football_live_match_data(r)
        result['pitchAPIStatus']={'configured':False,'ok':False,'error':'Aggiungi PITCHAPI_API_KEY a config.env per attivare PitchAPI'}
    else:
        result['liveMatch']={'available':False,'isLive':False,'reason':'Partita non in data odierna'}
        result['pitchAPIStatus']={'configured':bool(PITCHAPI_API_KEY),'ok':None,'error':None}
    histories={}
    history_diagnostics=[]
    pitch_history_count=0
    for side in ('home','away'):
        tid=(e or {}).get(side+'Team',{}).get('id')
        if not tid:tid=sofa_team_id_for_name(r[side])
        sofa_rows=player_history(tid) if tid else []
        pitch_rows=pitchapi_player_history(r[side],target_date=r.get('date'),limit=8) if PITCHAPI_API_KEY else []
        pitch_history_count+=len(pitch_rows)
        api_rows=api_football_player_history(r[side]) if API_FOOTBALL_KEY else []
        side_rows={}
        # Prefer PitchAPI first: its match-level data is consistent across the last
        # matches and doesn't require a paid plan for Serie A.
        for row in pitch_rows:
            if row.get('id') is not None:
                entry=dict(row);entry['_historyProvider']='PitchAPI'
                side_rows['pitch:'+str(row['id'])+':'+_player_name_key(row.get('name'))]=entry
        for row in api_rows:
            if row.get('id') is not None:
                entry=dict(row);entry['_historyProvider']='API-Football'
                side_rows['api:'+str(row['id'])+':'+_player_name_key(row.get('name'))]=entry
        for row in sofa_rows:
            if row.get('id') is not None:
                entry=dict(row);entry['_historyProvider']='SofaScore'
                side_rows['sofa:'+str(row['id'])+':'+_player_name_key(row.get('name'))]=entry
        histories[side]=side_rows
        history_diagnostics.append(f"{r[side]}: PitchAPI {len(pitch_rows)} giocatori; SofaScore {len(sofa_rows)}; API-Football {len(api_rows)}")
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
        hist=None
        if p.get('name'):
            pname=_player_name_key(p.get('name'))
            # Names are cross-provider identifiers; prefer API-Football season data.
            exact=[v for v in side_hist.values() if _player_name_key(v.get('name'))==pname]
            if exact:
                hist=next((v for v in exact if v.get('_historyProvider')=='PitchAPI'),
                     next((v for v in exact if v.get('_historyProvider')=='API-Football'),exact[0]))
            if not hist:
                # Fantacalcio abbreviates first names in probable lineups (e.g. Esposito F.P.).
                # Match only a unique shared surname/token to avoid assigning another player.
                name_parts=pname.split()
                tokens=[t for t in name_parts if len(t)>2]
                initials=[t for t in name_parts if len(t)<=2]
                matches=[]
                for v in side_hist.values():
                    vtokens=_player_name_key(v.get('name')).split()
                    long_tokens=[t for t in vtokens if len(t)>2]
                    if tokens and long_tokens and tokens[-1] in long_tokens:
                        # Probable lineup abbreviations can include initials after the surname:
                        # "Martinez Jo." or "Esposito F.P.". Use those initials to disambiguate.
                        if initials and not all(any(full.startswith(initial) for full in long_tokens if full!=tokens[-1]) for initial in initials):
                            continue
                        matches.append(v)
                # Deduplicate same player when both providers contain a row.
                unique={}
                for v in matches:
                    unique[_player_name_key(v.get('name'))]=v
                if len(unique)==1:
                    vals=list(unique.values())
                    hist=next((v for v in vals if v.get('_historyProvider')=='PitchAPI'),
                         next((v for v in vals if v.get('_historyProvider')=='API-Football'),vals[0]))
        if not hist or _stat_float(hist.get('minutes'))<=0:
            if p.get('fromProbableSource'):
                p['position']=p.get('position') or '—'
                p['starterProbability']=float(p.get('starterProbability') or 0)
                p['expectedMinutes']=None
                p['propCandidates']=[]
                if not PITCHAPI_API_KEY and not API_FOOTBALL_KEY:
                    why='PITCHAPI_API_KEY non configurata; fonti di riserva senza storico corrispondente'
                else:
                    why='nessuna riga statistica corrispondente trovata nei provider'
                p['dataBasis']='Storico non trovato: '+why
                result['players'].append(p)
            continue
        if p.get('fromProbableSource'):
            starter_pct=float(p.get('starterProbability') or 0.0)
            expected_min=max(5.0,min(90.0,float(hist.get('avgMinutes') or 0.0)))
        elif lu:
            starter=not bool(p.get('substitute',False)); starter_pct=100.0 if starter else 0.0; expected_min=78 if starter else 28
        else:
            starter_pct=float(hist.get('starterPct') or 0.0); expected_min=max(5.0,min(90.0,float(hist.get('avgMinutes') or 0.0))); starter=starter_pct>=50.0
        def per90(field):
            # Prefer provider-calculated rates; derive a rate only when its raw
            # total is actually present. Missing is not zero.
            direct=hist.get(field+'90')
            if direct is not None:return float(direct)
            total=hist.get(field);mins=hist.get('minutes')
            if total is None or mins is None or _stat_float(mins)<=0:return None
            return round(_stat_float(total)/_stat_float(mins)*90,2)
        p['history']={'apps':hist.get('apps'),'starts':hist.get('starts'),'minutes':hist.get('minutes'),
                      'starterPct':starter_pct,'avgMinutes':hist.get('avgMinutes'),
                      'fouls90':per90('fouls'),'fouled90':per90('fouled'),
                      'shots90':per90('shots'),'sot90':per90('sot'),
                      'cards90':per90('cards'),'goals90':per90('goals'),
                      'assists90':per90('assists'),'xg90':per90('xg')}
        def prob_over(lam,line):
            return max(0.0,min(1.0,1-sum(pois(k,lam) for k in range(int(line)+1))))
        rates=[('Falli commessi',p['history']['fouls90']),('Falli subiti',p['history']['fouled90']),
               ('Tiri',p['history']['shots90']),('Tiri in porta',p['history']['sot90']),
               ('Cartellini',p['history']['cards90']),('Gol',p['history']['goals90']),('Assist',p['history']['assists90'])]
        lines_by={'Falli commessi':(0.5,1.5,2.5),'Falli subiti':(0.5,1.5,2.5),
                  'Tiri':(0.5,1.5,2.5),'Tiri in porta':(0.5,1.5),
                  'Cartellini':(0.5,1.5),'Gol':(0.5,1.5),'Assist':(0.5,1.5)}
        props=[]
        for label,rate in rates:
            # Do not manufacture a 0.0 rate where the provider supplied no value.
            if rate is None:continue
            lam=max(0.0,float(rate)*expected_min/90)
            for line in lines_by[label]:
                pr=prob_over(lam,line)
                props.append({'market':f'{label} O{line}','prob':round(pr*100,1),'lambda':round(lam,2)})
        p['expectedMinutes']=round(expected_min)
        p['starterProbability']=round(starter_pct,1)
        p['propCandidates']=sorted(props,key=lambda x:x['prob'],reverse=True)
        p['foulProbability']=next((x['prob'] for x in props if x['market']=='Falli commessi O0.5'),None)
        p['cardProbability']=next((x['prob'] for x in props if x['market']=='Cartellini O0.5'),None)
        sample_note='campione limitato' if _stat_float(hist.get('minutes'))<180 else 'campione storico'
        provider_note=hist.get('_historyProvider') or 'SofaScore'
        seasons_note=(', stagioni '+','.join(str(x) for x in hist.get('historySeasons',[]))) if hist.get('historySeasons') else ''
        p['dataBasis']=(f"Fantacalcio.it · {hist.get('apps')} gare · {hist.get('starts',0)} da titolare · {int(_stat_float(hist.get('minutes')))} minuti · {provider_note}{seasons_note} · {sample_note}" if p.get('fromProbableSource') else f"{hist.get('apps')} gare · {hist.get('starts',0)} da titolare · {int(_stat_float(hist.get('minutes')))} minuti · {provider_note}{seasons_note} · {sample_note}")
        result['players'].append(p)

    result['available']=bool(e or result['players'])
    result['players']=sorted(result['players'],key=lambda x:(x['team'],not bool(x.get('substitute')), -float(x.get('starterProbability') or 0),-(x.get('history',{}).get('minutes') or 0)))
    if candidates and not lu:
        result['notes'].append('Probabili formazioni e percentuali di titolarità da Fantacalcio.it; non sono formazioni ufficiali.'+(f' Ultimo aggiornamento fonte: {probable_updated}.' if probable_updated else ''))
    elif not lu: result['notes'].append('Formazioni ufficiali non ancora disponibili: le stime migliorano quando la formazione è confermata.')
    matched=sum(1 for item in result['players'] if item.get('history'))
    probable_count=len(probable_candidates)
    if PITCHAPI_API_KEY:
        result['pitchAPIStatus']={'configured':True,'ok':pitch_history_count>0 or bool(result.get('liveMatch',{}).get('isLive')),
                                  'playersFound':pitch_history_count,
                                  'error':PITCHAPI_LAST_ERROR or PITCHAPI_LAST_STATUS.get('error'),
                                  'diagnostics':history_diagnostics}
    result['notes'].append(f"Storico giocatori trovato: {matched}/{probable_count if probable_count else len(result['players'])}. "+('PitchAPI configurata come fonte principale.' if PITCHAPI_API_KEY else 'PitchAPI non configurata.')+' Diagnostica: '+'; '.join(history_diagnostics)+'.'+(f" Stato PitchAPI: {str(PITCHAPI_LAST_STATUS)[:220]}." if PITCHAPI_API_KEY and matched < (probable_count or len(result['players'])) else '')+(f" Stato API-Football: {str(API_FOOTBALL_LAST_STATUS)[:180]}." if API_FOOTBALL_KEY and matched < (probable_count or len(result['players'])) else ''))
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
@app.get('/api/pitchapi-status')
def api_pitchapi_status():
    if not PITCHAPI_API_KEY:
        return jsonify(ok=True,data={'configured':False,'ok':False,
            'message':'PITCHAPI_API_KEY non configurata nel file config.env.','error':None})
    league=pitchapi_serie_a()
    if not league:
        return jsonify(ok=True,data={'configured':True,'ok':False,
            'message':'Chiave configurata ma impossibile recuperare il catalogo campionati.',
            'error':PITCHAPI_LAST_ERROR or PITCHAPI_LAST_STATUS.get('error') or PITCHAPI_LAST_STATUS})
    played=pitchapi_league_matches(league['id'],league['season'],status='played')
    upcoming=pitchapi_league_matches(league['id'],league['season'],status='upcoming')
    sample={'playerRows':0,'match':None,'ok':False}
    # Also test an actual match/player-stat endpoint; a league listing alone is not
    # enough to consider the integration healthy.
    for m in sorted(played,key=lambda x:str(x.get('date') or ''),reverse=True)[:3]:
        mid=m.get('id')
        if not mid:continue
        rows=pitchapi_get('/matches/'+str(mid)+'/players',ttl=30*86400)
        if isinstance(rows,list) and rows:
            sample={'playerRows':len(rows),'match':str((m.get('home_team') or {}).get('name',''))+' - '+str((m.get('away_team') or {}).get('name','')),
                    'matchId':mid,'ok':True}
            break
    ok=bool(played or upcoming) and sample['ok']
    if sample['ok']:
        message='Connessione e statistiche individuali PitchAPI verificate.'
    elif played or upcoming:
        message='Chiave e campionato raggiungibili, ma il test non ha trovato statistiche individuali nelle ultime partite campione.'
    else:
        message='Serie A trovata, ma la lista partite è vuota. Controlla stagione/copertura.'
    return jsonify(ok=True,data={'configured':True,'ok':ok,'league':league['name'],
        'leagueId':league['id'],'season':league['season'],'playedMatches':len(played),
        'upcomingMatches':len(upcoming),'playerRows':sample['playerRows'],'sampleMatch':sample.get('match'),
        'message':message,'providerStatus':PITCHAPI_LAST_STATUS,
        'error':None if sample['ok'] else PITCHAPI_LAST_ERROR or PITCHAPI_LAST_STATUS.get('error')})
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