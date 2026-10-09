
    # Keep early-season estimates anchored to the league, but do not collapse
    # genuine strength differences. More verified xG observations => less shrink.
    wh=sample_weight(hp,'home'); wa=sample_weight(ap,'away')
    raw_h=sa['home_xg']+(raw_h-sa['home_xg'])*wh
    raw_a=sa['away_xg']+(raw_a-sa['away_xg'])*wa

    # Final finishing/form correction is intentionally small.
    if hp.get('home_gf') is not None:
        raw_h=.92*raw_h+.08*hp['home_gf']
    if ap.get('away_gf') is not None:
        raw_a=.92*raw_a+.08*ap['away_gf']

    # Strength prior: early-season shot/xG proxies can make a strong side look
    # artificially similar to a weaker opponent. The adjustment is bounded and
    # uses only football statistics, never bookmaker prices.
    home_strength=team_strength_score(d,h)
    away_strength=team_strength_score(d,a)
    strength_diff=max(-1.5,min(1.5,away_strength-home_strength))
    strength_factor=0.55
    raw_h *= math.exp(-strength_factor*strength_diff)
    raw_a *= math.exp( strength_factor*strength_diff)

    return max(.15,min(4.5,raw_h)),max(.10,min(4.0,raw_a))

def pois(k,l):return math.exp(-l)*l**k/math.factorial(k)

def score_matrix(h,a,rho=-0.12):
    m=[[pois(i,h)*pois(j,a) for j in range(10)] for i in range(10)]
    # Dixon-Coles low-score correction, then renormalize.
    corr={(0,0):1-h*a*rho,(1,0):1+a*rho,(0,1):1+h*rho,(1,1):1-rho}
    for (i,j),c in corr.items():m[i][j]*=max(0.2,c)
    z=sum(map(sum,m));return [[v/z for v in row] for row in m]

def markets(h,a):
    m=score_matrix(h,a);p={};mg={}
    for i,row in enumerate(m):
        for j,v in enumerate(row):
            p['1']=p.get('1',0)+(v if i>j else 0);p['X']=p.get('X',0)+(v if i==j else 0);p['2']=p.get('2',0)+(v if i<j else 0)
            p['GG']=p.get('GG',0)+(v if i>0 and j>0 else 0);p['NG']=p.get('NG',0)+(v if i==0 or j==0 else 0);mg[i+j]=mg.get(i+j,0)+v
    p.update({'1X':p['1']+p['X'],'X2':p['X']+p['2'],'12':p['1']+p['2']})
    # Keep only the requested O/U lines in the public market matrix.
    for n in (1,2,3):
        p[f'O{n}.5']=sum(v for g,v in mg.items() if g>n)
        if n in (2,3):
            p[f'U{n}.5']=sum(v for g,v in mg.items() if g<=n)
    # Multigol is split into: total match, home team goals, away team goals.
    home_goals={i:sum(row[i] for row in m) for i in range(10)}
    away_goals={j:sum(m[i][j] for i in range(10)) for j in range(10)}
    for lo,hi in [(1,2),(1,3),(1,4),(2,3),(2,4),(2,5),(3,4),(3,5),(3,6),(4,5),(4,6)]:
        p[f'MG{lo}-{hi}']=sum(v for g,v in mg.items() if lo<=g<=hi)
        p[f'MGH{lo}-{hi}']=sum(v for g,v in home_goals.items() if lo<=g<=hi)
        p[f'MGA{lo}-{hi}']=sum(v for g,v in away_goals.items() if lo<=g<=hi)
    combos={'1X+O1.5':('1X','O1.5'),'X2+O1.5':('X2','O1.5'),'1X+U3.5':('1X','U3.5'),'X2+U3.5':('X2','U3.5'),'12+O1.5':('12','O1.5'),'GG+O2.5':('GG','O2.5'),'NG+U3.5':('NG','U3.5')}
    for key,(c1,c2) in combos.items():
        total=0
        for i,row in enumerate(m):
            for j,v in enumerate(row):
                c1ok={'1X':i>=j,'X2':i<=j,'12':i!=j,'GG':i>0 and j>0,'NG':i==0 or j==0}[c1]
                g=i+j;c2ok=(g>=2 if c2=='O1.5' else g<=3 if c2=='U3.5' else g>=3 if c2=='O2.5' else g<=3)
                if c1ok and c2ok:total+=v
        p[key]=total
    return p

def _odds_cache_load():
    try:return json.load(open(ODDS_CACHE,encoding='utf-8'))
    except:return {}

def _odds_cache_save(c):
    try:json.dump(c,open(ODDS_CACHE,'w',encoding='utf-8'),ensure_ascii=False)
    except Exception:pass

def api_football_get(path,ttl=1800):
    global API_FOOTBALL_LAST_ERROR, API_FOOTBALL_LAST_STATUS
    if not API_FOOTBALL_KEY:
        API_FOOTBALL_LAST_ERROR='API_FOOTBALL_KEY non configurata'
        API_FOOTBALL_LAST_STATUS={'configured':False,'path':path}
        return None
    cache=_odds_cache_load();key=path;now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<ttl:
        API_FOOTBALL_LAST_STATUS={'configured':True,'cached':True,'path':path,'http':200}
        return v.get('data')
    try:
        req=Request(API_FOOTBALL+path,headers={'x-apisports-key':API_FOOTBALL_KEY,'User-Agent':'FootballAnalyzer/PRO'})
        with urlopen(req,timeout=20) as resp:
            data=json.loads(resp.read().decode('utf-8'))
            code=getattr(resp,'status',200)
        api_errors=(data.get('errors') if isinstance(data,dict) else None) or {}
        if api_errors:
            API_FOOTBALL_LAST_ERROR=json.dumps(api_errors,ensure_ascii=False)
        else:
            API_FOOTBALL_LAST_ERROR=''
        API_FOOTBALL_LAST_STATUS={'configured':True,'cached':False,'path':path,'http':code,'results':(data.get('results') if isinstance(data,dict) else None),'errors':api_errors}
        cache[key]={'ts':now,'data':data};_odds_cache_save(cache);return data
    except Exception as e:
        API_FOOTBALL_LAST_ERROR=str(e)
        API_FOOTBALL_LAST_STATUS={'configured':True,'cached':False,'path':path,'http':None,'errors':{'exception':str(e)}}
        return None

def _context_cache_load(path=CONTEXT_CACHE):
    try:return json.load(open(path,encoding='utf-8'))
    except:return {}
def _context_cache_save(c,path=CONTEXT_CACHE):
    try:json.dump(c,open(path,'w',encoding='utf-8'),ensure_ascii=False)
    except Exception:pass

def api_football_season_fixtures():
    if not API_FOOTBALL_KEY:return []
    # Cache versioned: older builds stored only page 1, which omitted many rounds.
    cache=_context_cache_load();key='season_fixtures_2026_v2';now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<6*3600 and len(v.get('data',[]))>=300:return v.get('data',[])
    first=api_football_get(f'/fixtures?league={API_FOOTBALL_LEAGUE}&season=2026&page=1',ttl=6*3600) or {}
    rows=list(first.get('response') or [])
    pagination=first.get('paging') or first.get('pagination') or {}
    try:pages=min(30,max(1,int(pagination.get('total') or 1)))
    except Exception:pages=1
    for page in range(2,pages+1):
        data=api_football_get(f'/fixtures?league={API_FOOTBALL_LEAGUE}&season=2026&page={page}',ttl=6*3600) or {}
        page_rows=data.get('response') or []
        if not page_rows:break
        rows.extend(page_rows)
    # Avoid replacing a useful cache with an incomplete provider response.
    if len(rows)>=300:
        cache[key]={'ts':now,'data':rows};_context_cache_save(cache)
        return rows
    old=cache.get(key,{}).get('data',[])
    if len(old)>len(rows):return old
    cache[key]={'ts':now,'data':rows};_context_cache_save(cache);return rows

def api_football_league_injuries():
    if not API_FOOTBALL_KEY:return []
    cache=_context_cache_load();key='league_injuries_2026';now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<4*3600:return v.get('data',[])
    data=api_football_get(f'/injuries?league={API_FOOTBALL_LEAGUE}&season=2026',ttl=4*3600) or {}
    rows=data.get('response') or []
    cache[key]={'ts':now,'data':rows};_context_cache_save(cache);return rows

def _api_fixture_for(r):
    rows=api_football_season_fixtures()
    hn,an=norm_team(r['home']),norm_team(r['away'])
    for item in rows:
        teams=item.get('teams') or {}
        h=norm_team((teams.get('home') or {}).get('name'));a=norm_team((teams.get('away') or {}).get('name'))
        if (h==hn and a==an) or (hn.lower() in h.lower() and an.lower() in a.lower()):return item
    return None

def api_football_odds_for(r):
    """Reference pre-match odds from API-Football.

    Bet365 is preferred when present, but it is NOT required: the engine now
    selects the bookmaker feed with the best market coverage and labels it as
    reference odds. No bookmaker website is scraped.
    """
    if not API_FOOTBALL_KEY:return {}
    target=_api_fixture_for(r)
    if not target:return {}
    fid=target.get('fixture',{}).get('id')
    if not fid:return {}
    data=api_football_get(f'/odds?fixture={fid}',ttl=900) or {}
    books=[]
    total_pages=max(1,int((data.get('paging') or {}).get('total',1)))
    for page in range(1,total_pages+1):
        page_data=data if page==1 else (api_football_get(f'/odds?fixture={fid}&page={page}',ttl=900) or {})
        response=page_data.get('response') or []
        if not response:continue
        for bm in (response[0].get('bookmakers') or []):
            name=str(bm.get('name') or 'Unknown')
            out={}
            for bet in bm.get('bets',[]):
                bname=str(bet.get('name') or '').lower()
                for v in bet.get('values') or []:
                    val=str(v.get('value') or '').strip().lower()
                    odd=v.get('odd')
                    try:odd=float(odd)
                    except Exception:continue
                    if odd<=1:continue
                    if bname in ('match winner','fulltime result','1x2'):
                        if val in ('home','1'):out['1']=odd
                        elif val in ('draw','x'):out['X']=odd
                        elif val in ('away','2'):out['2']=odd
                    elif 'both teams' in bname and 'score' in bname:
                        if val in ('yes','gg'):out['GG']=odd
                        elif val in ('no','ng'):out['NG']=odd
                    elif 'over/under' in bname or 'goals over/under' in bname or 'total goals' in bname:
                        m=re.match(r'(over|under)\s+(\d+(?:\.5)?)',val,re.I)
                        if m:
                            pref='O' if m.group(1).lower()=='over' else 'U'
                            half='H1' if ('first half' in bname or '1st half' in bname) else 'H2' if ('second half' in bname or '2nd half' in bname) else ''
                            out[half+pref+m.group(2)]=odd
                    elif ('shots on target' in bname or 'shots on goal' in bname or 'total shots' in bname or bname.strip()=='shots') and ('first half' in bname or '1st half' in bname or 'second half' in bname or '2nd half' in bname):
                        m=re.match(r'(over|under)\s+(\d+(?:\.5)?)',val,re.I)
                        if m:
                            pref='O' if m.group(1).lower()=='over' else 'U'; half='H1' if ('first half' in bname or '1st half' in bname) else 'H2'
                            kind='SOT' if ('shots on target' in bname or 'shots on goal' in bname) else 'TS'
                            out[f'{half}{kind}_{pref}{m.group(2)}']=odd
                    elif any(k in bname for k in ('multi goals','multigoals','goal range','goals range','total goals range')):
                        m=re.search(r'(\d+)\s*[-–]\s*(\d+)',val)
                        if m:out[f"MG{m.group(1)}-{m.group(2)}"]=odd
            if out:books.append((name,out))
    if not books:return {}
    # Prefer Bet365 only when it has useful coverage; otherwise use the bookmaker
    # with the largest number of model-supported markets.
    preferred=[b for b in books if 'bet365' in b[0].lower()]
    chosen=max(preferred or books,key=lambda b:len(b[1]))
    out=dict(chosen[1]);out['_bookmaker']=chosen[0];out['_odds_source']='API-Football reference odds'
    return out

def api_football_match_context(r):
    """Cached fixture context. Injuries are fetched once per league/season, not once per match."""
    if not API_FOOTBALL_KEY:return {'available':False,'reason':'API key non configurata'}
    target=_api_fixture_for(r)
    if not target:return {'available':False,'reason':'fixture API-Football non trovato'}
    fid=target.get('fixture',{}).get('id')
    if not fid:return {'available':False,'reason':'fixture id non disponibile'}
    teams=target.get('teams') or {};h_id=(teams.get('home') or {}).get('id');a_id=(teams.get('away') or {}).get('id')
    # SofaScore uses a different team-id namespace. Resolve it once from the match event
    # so player importance/history never mixes provider IDs.
    sofa_event=sofa_event_for(r)
    sofa_ids={'home':(sofa_event or {}).get('homeTeam',{}).get('id'),'away':(sofa_event or {}).get('awayTeam',{}).get('id')}
    all_inj=api_football_league_injuries()
    inj=[]
    for item in all_inj:
        tm=(item.get('team') or {}).get('id');fx=(item.get('fixture') or {}).get('id')
        if tm in (h_id,a_id) and (fx in (None,fid) or not fx):inj.append(item)
    return {'available':True,'fixture_id':fid,'home_id':h_id,'away_id':a_id,'injuries':inj,'prediction':None}

def _news_cache_load():return _context_cache_load(NEWS_CACHE)
def _news_cache_save(c):_context_cache_save(c,NEWS_CACHE)

def team_news(team,limit=8):
    cache=_news_cache_load();key=norm_team(team);now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<1800:return v.get('items',[])
    try:
        q=quote_plus(f'"{team}" Serie A (infortunio OR infortunato OR squalificato OR assente OR recuperato OR rientra OR convocato)')
        raw=get('https://news.google.com/rss/search?q='+q+'&hl=it&gl=IT&ceid=IT:it')
        root=ET.fromstring(raw);items=[]
        for it in root.findall('.//item')[:limit]:
            items.append({'title':it.findtext('title') or '','link':it.findtext('link') or '','date':it.findtext('pubDate') or '','source':it.findtext('source') or ''})
    except Exception:items=[]
    cache[key]={'ts':now,'items':items};_news_cache_save(cache);return items

NEG_NEWS=('infortun','lesione','squalificat','assente','non convocat','stop','out','salta','indisponibile','ko')
POS_NEWS=('recuperat','rientr','convocat','in gruppo','disponibile','torna')
def _news_signal(items):
    neg=pos=0;relevant=[]
    for x in items:
        title=(x.get('title') or '').lower()
        n=sum(1 for k in NEG_NEWS if k in title);p=sum(1 for k in POS_NEWS if k in title)
        if n or p:
            neg+=min(2,n);pos+=min(2,p);relevant.append(x)
    return max(-1,min(1,(pos-neg)*0.20)),relevant

def _name_key(s):return re.sub(r'[^a-z0-9]','',str(s or '').lower())
def _cached_player_history(team_id):
    if not team_id:return []
    cache=_context_cache_load();key=f'player_history_{team_id}';now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<12*3600:return v.get('data',[])
    try:data=player_history(team_id)
    except Exception:data=[]
    cache[key]={'ts':now,'data':data};_context_cache_save(cache);return data

def player_importance_for_team(team_id,player_name,hist=None):
    if not team_id or not player_name:return 0.35
    hist=hist if hist is not None else _cached_player_history(team_id)
    target=_name_key(player_name);best=None
    for p in hist:
        k=_name_key(p.get('name'))
        if k==target or target in k or k in target:
            mins=p.get('minutes',0) or 0;shots=p.get('shots',0) or 0;goals=p.get('goals',0) or 0;assists=p.get('assists',0) or 0
            total_mins=sum((x.get('minutes',0) or 0) for x in hist) or 1
            total_ga=sum((x.get('goals',0) or 0)+(x.get('assists',0) or 0) for x in hist) or 1
            total_shots=sum((x.get('shots',0) or 0) for x in hist) or 1
            score=.55*(mins/total_mins)+.25*((goals+assists)/total_ga)+.20*(shots/total_shots)
            best=max(0.10,min(1.0,score*3.0));break
    return best if best is not None else 0.35

def availability_context(d,r):
    ctx=api_football_match_context(r);inj=ctx.get('injuries',[]) if ctx.get('available') else []
    teams_by_side={r['home']:'home',r['away']:'away'};team_ids={}
    impact={side:{'attack':0.0,'defense':0.0} for side in ('home','away')}
    sofa_ids=ctx.get('sofa_ids') or {}
    for side in ('home','away'):
        if sofa_ids.get(side):team_ids[side]=sofa_ids[side]
    details=[]
    for item in inj:
        tm=item.get('team') or {};name=norm_team(tm.get('name'));side=teams_by_side.get(name)
        if side and not team_ids.get(side):team_ids[side]=tm.get('id')
    for item in inj:
        tm=item.get('team') or {};side=teams_by_side.get(norm_team(tm.get('name')))
        if not side:continue
        player=(item.get('player') or {});name=player.get('name') or 'Giocatore'
        hist=_cached_player_history(team_ids.get(side))
        importance=player_importance_for_team(team_ids.get(side),name,hist)
        role='unknown'
        try:
            nk=_name_key(name)
            match=next((x for x in hist if _name_key(x.get('name'))==nk or nk in _name_key(x.get('name')) or _name_key(x.get('name')) in nk),None)
            role=str(match.get('position') or 'unknown').lower() if match else 'unknown'
        except Exception:pass
        typ=str(item.get('type') or '').lower()
        severity=1.0 if 'susp' in typ else 0.9
        w=importance*severity
        if any(k in role for k in ('goalkeeper','defender','centre-back','center-back','full-back','wing-back')):
            impact[side]['defense']+=w
        elif any(k in role for k in ('forward','attacker','striker')):
            impact[side]['attack']+=w
        else:
            impact[side]['attack']+=w*0.55;impact[side]['defense']+=w*0.45
        details.append({'team':r[side],'player':name,'type':item.get('type'),'reason':item.get('reason'),'importance':round(importance,2),'role':role})
    # News is a secondary confirmation layer. It never overrides confirmed injury data.
    for side,team in [('home',r['home']),('away',r['away'])]:
        sig,items=_news_signal(team_news(team))
        if sig<0:
            impact[side]['attack']+=abs(sig)*0.35;impact[side]['defense']+=abs(sig)*0.20
        elif sig>0:
            impact[side]['attack']=max(0,impact[side]['attack']-sig*0.25);impact[side]['defense']=max(0,impact[side]['defense']-sig*0.15)
        for x in items[:3]:details.append({'team':team,'news':x.get('title'),'source':x.get('source')})
    # Hard bounds keep news/injury context as a modifier, never the dominant model.
    for side in impact:
        for k in impact[side]:impact[side][k]=round(max(0,min(2.0,impact[side][k])),3)
    return {'home_attack_loss':impact['home']['attack'],'home_defense_loss':impact['home']['defense'],
            'away_attack_loss':impact['away']['attack'],'away_defense_loss':impact['away']['defense'],
            'details':details,'prediction':ctx.get('prediction'),'available':ctx.get('available',False)}

def odds_for(r):
    out={}
    for k,v in [('1','bh'),('X','bd'),('2','ba'),('O2.5','bo'),('U2.5','bu')]:
        if r.get(v) is not None:out[k]=r[v]
    live=api_football_odds_for(r)
    if live:out.update(live)
    return out

def market_signal_score(d,r,p,market):
    hp=team_profile(d,r['home']);ap=team_profile(d,r['away']);xh,xa=xg(d,r['home'],r['away']);total=xh+xa;diff=xh-xa
    formdiff=hp['form']-ap['form']
    hc=half_context_for_match(r)
    # Use multiple independent dimensions so a market needs a coherent scenario.
    def z(v,s): return max(-1,min(1,v/max(s,.001)))
    if hc.get('available'):
        hh,aa=hc['home'],hc['away']
        start=z((hh.get('start_index') or 0)-(aa.get('start_index') or 0),.8)
        late=z((hh.get('second_index') or 0)-(aa.get('second_index') or 0),.8)