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
    data=sofa_get('/sport/football/scheduled-events/'+r['date'],ttl=900)
    if not data:return None
    def nm(x):return norm_team(x)
    for e in data.get('events',[]):
        h=nm(e.get('homeTeam',{}).get('name'));a=nm(e.get('awayTeam',{}).get('name'))
        if h==r['home'] and a==r['away']:return e
    return None

def player_stats_from_lineup(lineup,side):
    rows=[]
    for item in (lineup.get(side,{}).get('players',[]) if lineup else []):
        p=item.get('player',{});s=item.get('statistics') or {};mins=s.get('minutesPlayed') or 0
        if not p.get('name'):continue
        rows.append({'id':p.get('id'),'name':p.get('name'),'position':p.get('position'),'substitute':item.get('substitute',False),'minutes':mins,'fouls':s.get('fouls'),'fouled':s.get('wasFouled'),'shots':s.get('totalShots') or s.get('shots'),'sot':s.get('shotsOnTarget'),'cards':s.get('yellowCards',0) or 0,'goals':s.get('goals',0) or 0,'assists':s.get('assists',0) or 0})
    return rows

def player_history(team_id):
    data=sofa_get(f'/team/{team_id}/events/last/0',ttl=1800)
    events=(data or {}).get('events',[])[:8];agg={}
    for e in events:
        if e.get('status',{}).get('type')!='finished':continue
        lu=sofa_get(f"/event/{e['id']}/lineups",ttl=7*86400)
        if not lu:continue
        side='home' if e.get('homeTeam',{}).get('id')==team_id else 'away'
        for s in player_stats_from_lineup(lu,side):
            if not s['minutes']:continue
            a=agg.setdefault(s['id'],dict(s,apps=0));a['apps']+=1
            for k in ('minutes','fouls','fouled','shots','sot','cards','goals','assists'):
                if s.get(k) is not None:a[k]=(a.get(k) or 0)+(s.get(k) or 0)
    out=[]
    for a in agg.values():
        mins=a['minutes'] or 1
        a['fouls90']=round((a.get('fouls') or 0)/mins*90,2);a['fouled90']=round((a.get('fouled') or 0)/mins*90,2);a['shots90']=round((a.get('shots') or 0)/mins*90,2);a['sot90']=round((a.get('sot') or 0)/mins*90,2);a['cards90']=round((a.get('cards') or 0)/mins*90,2);out.append(a)
    return sorted(out,key=lambda x:x['minutes'],reverse=True)

def player_props(d,r):
    e=sofa_event_for(r);result={'available':False,'source':'SofaScore public endpoints','eventId':e.get('id') if e else None,'referee':(e or {}).get('referee',{}).get('name'),'players':[],'notes':[]}
    if not e:
        result['notes'].append('Contesto giocatori non disponibile per questa partita; il modello non inventa dati.')
        return result
    lu=sofa_get(f"/event/{e['id']}/lineups",ttl=900)
    if not lu:
        result['notes'].append('Formazioni non ancora disponibili o endpoint non raggiungibile.')
        return result
    result['available']=True
    for side,team in [('home',r['home']),('away',r['away'])]:
        for p in player_stats_from_lineup(lu,side):
            # current lineup is only used as a candidate list; history provides the rates
            result['players'].append(dict(p,team=team,side=side))
    # Historical player rates: aggregate recent finished matches for the two teams.
    histories={}
    for side in ('home','away'):
        tid=e.get(side+'Team',{}).get('id')
        if tid: histories[tid]={x['id']:x for x in player_history(tid)}
    for p in result['players']:
        tid=e.get(p['side']+'Team',{}).get('id'); hist=histories.get(tid,{}).get(p.get('id'))
        if not hist or hist.get('minutes',0)<120:
            p['propCandidates']=[];continue
        # Starters/substitutes are inferred from the lineup flag when available.
        starter=not bool(p.get('substitute',False)); expected_min=78 if starter else 28
        lf=max(0.05,(hist.get('fouls90') or 0)*expected_min/90)
        lw=max(0.05,(hist.get('fouled90') or 0)*expected_min/90)
        def prob_over(lam,line):
            return 1-sum(pois(k,lam) for k in range(int(line)+1))
        p['history']={'apps':hist.get('apps'),'minutes':hist.get('minutes'),'fouls90':hist.get('fouls90'),'fouled90':hist.get('fouled90'),'shots90':hist.get('shots90'),'cards90':hist.get('cards90')}
        props=[]
        for label,lam in [('Falli commessi',lf),('Falli subiti',lw)]:
            for line in (0.5,1.5,2.5):
                props.append({'market':f'{label} O{line}','prob':round(prob_over(lam,line)*100,1),'lambda':round(lam,2),'basis':f'{hist.get("apps")} gare · {hist.get("fouls90") if label=="Falli commessi" else hist.get("fouled90")} per 90'})
        p['propCandidates']=props
    result['notes'].append('Le player-probability sono stime Poisson sui tassi recenti del giocatore e minuti attesi; non sono garanzie e vengono mostrate solo con storico sufficiente.')
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
    d=load();return jsonify(ok=True,data={'updated':d.get('updated'),'played':len(current(d)),'upcoming':len(upcoming(d)),'teams':len(teams(d)),'schedule':len(d.get('schedule',[])),'errors':d.get('errors',[]),'validation':d.get('validation',{}),'updater':d.get('updater',{})})
@app.post('/api/refresh')
def api_refresh():
    try:return jsonify(ok=True,data={'updated':refresh(force_stats=True).get('updated'),'played':len(current(load())),'upcoming':len(upcoming(load())),'teams':len(teams(load())),'schedule':len(load().get('schedule',[])),'errors':load().get('errors',[])})
    except Exception as e:return jsonify(ok=False,error=str(e)),500
@app.get('/api/matches')
def api_matches():
    d=load();mp={(r['date'],r['home'],r['away']):r['round'] for r in d['schedule']};out=[]
    for r in upcoming(d):
        rr=dict(r);rr['round']=mp.get((r['date'],r['home'],r['away']));out.append(model_obj(d,rr))
    return jsonify(ok=True,matches=out)
@app.get('/api/rounds')
def api_rounds():
    d=load();pk={(r['date'],r['home'],r['away']) for r in current(d)};groups={}
    for r in d['schedule']:
        x=model_obj(d,r);x['status']='played' if (r['date'],r['home'],r['away']) in pk else ('upcoming' if r['date']>=date.today().isoformat() else 'past');groups.setdefault(r['round'],[]).append(x)
    rows=[]
    for n,ms in sorted(groups.items()):rows.append({'round':n,'status':'upcoming' if any(x['status']=='upcoming' for x in ms) else 'played' if all(x['status']=='played' for x in ms) else 'past','matches':ms})
    return jsonify(ok=True,rounds=rows)
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
    d=load();h=request.args.get('home');a=request.args.get('away');dt=request.args.get('date');r=next((x for x in d['schedule'] if x['home']==h and x['away']==a and x['date']==dt),None)
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