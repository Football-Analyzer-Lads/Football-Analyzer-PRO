    except Exception:return {'matches':0}
    events=[]
    for e in data.get('events',[]):
        if e.get('status',{}).get('type')!='finished':continue
        side='home' if e.get('homeTeam',{}).get('id')==team_id else 'away' if e.get('awayTeam',{}).get('id')==team_id else None
        if not side:continue
        if venue=='home' and side!='home':continue
        if venue=='away' and side!='away':continue
        events.append(e)
        if len(events)>=n:break
    def av(xs):return _wavg(xs) if xs else None
    buckets={k:[] for k in ('gfor1','gcon1','gfor2','gcon2','shots1','shots_against1','shots2','shots_against2','sot1','sot_against1','sot2','sot_against2','xg1','xga1','xg2','xga2')}
    first_scored=[];first_clean=[];second_scored=[]
    used=0
    for e in events:
        try:half=sofa_match_half_statistics(e.get('id')) or {}
        except Exception:half={}
        side='home' if e.get('homeTeam',{}).get('id')==team_id else 'away'
        hs=e.get('homeScore') or {};as_=e.get('awayScore') or {}
        final_h=hs.get('current',hs.get('normaltime',hs.get('display',0))) or 0
        final_a=as_.get('current',as_.get('normaltime',as_.get('display',0))) or 0
        p1h=hs.get('period1');p1a=as_.get('period1')
        if p1h is None or p1a is None:continue
        p1h=float(p1h);p1a=float(p1a)
        p2h=max(0,float(final_h)-p1h);p2a=max(0,float(final_a)-p1a)
        if side=='home':
            g1,g1c,g2,g2c=p1h,p1a,p2h,p2a
        else:g1,g1c,g2,g2c=p1a,p1h,p2a,p2h
        buckets['gfor1'].append(g1);buckets['gcon1'].append(g1c);buckets['gfor2'].append(g2);buckets['gcon2'].append(g2c)
        first_scored.append(1 if g1>0 else 0);first_clean.append(1 if g1c==0 else 0);second_scored.append(1 if g2>0 else 0)
        ok=False
        for per,keyown,keyopp in [('1ST','shots1','shots_against1'),('2ND','shots2','shots_against2')]:
            st=half.get(per) or {}
            sh=st.get('shots');sot=st.get('sot')
            if sh and sh[0] is not None and sh[1] is not None:
                buckets[keyown].append(sh[0] if side=='home' else sh[1]);buckets[keyopp].append(sh[1] if side=='home' else sh[0]);ok=True
            if sot and sot[0] is not None and sot[1] is not None:
                own=sot[0] if side=='home' else sot[1];opp=sot[1] if side=='home' else sot[0]
                buckets['sot1' if per=='1ST' else 'sot2'].append(own);buckets['sot_against1' if per=='1ST' else 'sot_against2'].append(opp)
            xg=st.get('xg')
            if xg and xg[0] is not None and xg[1] is not None:
                buckets['xg1' if per=='1ST' else 'xg2'].append(xg[0] if side=='home' else xg[1]);buckets['xga1' if per=='1ST' else 'xga2'].append(xg[1] if side=='home' else xg[0])
        used+=1
    result={'matches':used,'first_gf':av(buckets['gfor1']),'first_ga':av(buckets['gcon1']),'second_gf':av(buckets['gfor2']),'second_ga':av(buckets['gcon2']),
            'first_scored_rate':av(first_scored),'first_clean_rate':av(first_clean),'second_scored_rate':av(second_scored),
            'first_shots':av(buckets['shots1']),'first_shots_against':av(buckets['shots_against1']),'second_shots':av(buckets['shots2']),'second_shots_against':av(buckets['shots_against2']),
            'first_sot':av(buckets['sot1']),'first_sot_against':av(buckets['sot_against1']),'second_sot':av(buckets['sot2']),'second_sot_against':av(buckets['sot_against2']),
            'first_xg':av(buckets['xg1']),'first_xga':av(buckets['xga1']),'second_xg':av(buckets['xg2']),'second_xga':av(buckets['xga2'])}
    # Composite tempo indices: goals/xG are primary, but shots/SoT also matter.
    # This avoids calling a team a 'slow starter' solely because of goals when its
    # first-half shot volume is actually high (or vice versa).
    def tempo_index(period):
        if period=='first':
            gf,ga,xgf,xga,sh,sha,sot,sota=(result.get('first_gf'),result.get('first_ga'),result.get('first_xg'),result.get('first_xga'),result.get('first_shots'),result.get('first_shots_against'),result.get('first_sot'),result.get('first_sot_against'))
        else:
            gf,ga,xgf,xga,sh,sha,sot,sota=(result.get('second_gf'),result.get('second_ga'),result.get('second_xg'),result.get('second_xga'),result.get('second_shots'),result.get('second_shots_against'),result.get('second_sot'),result.get('second_sot_against'))
        signals=[]
        if xgf is not None and xga is not None: signals.append((xgf-xga)/1.0*0.50)
        elif gf is not None and ga is not None: signals.append((gf-ga)/1.0*0.50)
        if sh is not None and sha is not None: signals.append((sh-sha)/8.0*0.25)
        if sot is not None and sota is not None: signals.append((sot-sota)/4.0*0.25)
        return max(-1,min(1,sum(signals))) if signals else 0.0
    result['start_index']=tempo_index('first')
    result['second_index']=tempo_index('second')
    cache[key]={'ts':now,'data':result};_context_cache_save(cache);return result

def half_context_for_match(r):
    e=sofa_event_for(r)
    if not e:return {'available':False,'reason':'SofaScore event non trovato'}
    hp=sofa_team_half_profile((e.get('homeTeam') or {}).get('id'),'home',6)
    ap=sofa_team_half_profile((e.get('awayTeam') or {}).get('id'),'away',6)
    return {'available':(hp.get('matches',0)>=2 and ap.get('matches',0)>=2),'home':hp,'away':ap,'sample':min(hp.get('matches',0),ap.get('matches',0))}

def half_market_probs(ctx):
    """Model-only first/second-half markets using total + home/away volume.

    H1/H2 TS and SOT are TOTALS (home + away), while the H1/H2 HS/AS variants
    are team-specific. They can become BEST only when a real reference quote exists.
    """
    if not ctx.get('available'):return {}
    hp,ap=ctx['home'],ctx['away']
    def blend(own,opp):
        return None if own is None or opp is None else max(.05,.58*own+.42*opp)
    def period_values(period):
        pre='first_' if period=='first' else 'second_'
        hts=blend(hp.get(pre+'shots'),ap.get(pre+'shots_against'))
        ats=blend(ap.get(pre+'shots'),hp.get(pre+'shots_against'))
        hsot=blend(hp.get(pre+'sot'),ap.get(pre+'sot_against'))
        asot=blend(ap.get(pre+'sot'),hp.get(pre+'sot_against'))
        return hts,ats,hsot,asot
    hts1,ats1,hsot1,asot1=period_values('first')
    hts2,ats2,hsot2,asot2=period_values('second')
    h1=((hp.get('first_xg') or hp.get('first_gf') or .0)+(ap.get('first_xga') or ap.get('first_ga') or .0))/2
    a1=((ap.get('first_xg') or ap.get('first_gf') or .0)+(hp.get('first_xga') or hp.get('first_ga') or .0))/2
    h2=((hp.get('second_xg') or hp.get('second_gf') or .0)+(ap.get('second_xga') or ap.get('second_ga') or .0))/2
    a2=((ap.get('second_xg') or ap.get('second_gf') or .0)+(hp.get('second_xga') or hp.get('second_ga') or .0))/2
    g1=max(.08,min(2.8,h1+a1));g2=max(.08,min(2.8,h2+a2))
    out={}
    for tag,lam in [('H1',g1),('H2',g2)]:
        for n in (0.5,1.5):
            out[f'{tag}O{n:.1f}']=_count_market_prob(lam,n,True);out[f'{tag}U{n:.1f}']=_count_market_prob(lam,n,False)
    for tag,hts,ats,hsot,asot in [('H1',hts1,ats1,hsot1,asot1),('H2',hts2,ats2,hsot2,asot2)]:
        for kind,hmean,amean in [('TS',hts,ats),('SOT',hsot,asot)]:
            if hmean is None or amean is None:continue
            total=hmean+amean
            for prefix,mean in [(kind,total),(('HS' if kind=='TS' else 'HSOT'),hmean),(('AS' if kind=='TS' else 'ASOT'),amean)]:
                for n in range(max(2,int(mean)-4),min(16,int(mean)+5)):
                    line=n+.5
                    out[f'{tag}{prefix}_O{line:.1f}']=_count_market_prob(mean,line,True)
                    out[f'{tag}{prefix}_U{line:.1f}']=_count_market_prob(mean,line,False)
    return out

def team_profile(d,t,n=12,venue='all'):
    hist=sorted([r for r in played(d) if t in (r['home'],r['away']) and (venue=='all' or (venue=='home' and r['home']==t) or (venue=='away' and r['away']==t))],key=lambda x:x['date'])
    rs=hist[-n:]
    if not rs:
        return {'matches':0,'gf':1.3,'ga':1.3,'home_gf':1.3,'home_ga':1.3,'away_gf':1.1,'away_ga':1.1,
                'form':0.5,'shots':None,'sot':None,'corners':None,'fouls':None,'yellow':None,
                'shots_against':None,'sot_against':None,'corners_against':None,'fouls_against':None,'yellow_against':None,'possession':None,'possession_against':None,'shots_off':None,'shots_off_against':None,'blocked':None,'blocked_against':None,
                'xg':None,'xg_against':None,'home_xg':None,'home_xga':None,'away_xg':None,'away_xga':None,
                'xg_matches':0,'verified_matches':0}
    gf=[];ga=[];pts=[];home_gf=[];home_ga=[];away_gf=[];away_ga=[]
    shots=[];shots_against=[];sots=[];sots_against=[];corn=[];corn_against=[];fouls=[];fouls_against=[];yellow=[];yellow_against=[];pos=[];pos_against=[];soff=[];soff_against=[];blocked=[];blocked_against=[]
    xgs=[];xgs_against=[];home_xg=[];home_xga=[];away_xg=[];away_xga=[]
    verified=0
    for r in rs:
        is_home=r['home']==t
        sc=r['hg'] if is_home else r['ag'];co=r['ag'] if is_home else r['hg']
        gf.append(sc);ga.append(co);pts.append(3 if sc>co else 1 if sc==co else 0)
        if is_home:home_gf.append(sc);home_ga.append(co)
        else:away_gf.append(sc);away_ga.append(co)
        if stats_verified(r):
            verified+=1
            def add(pair, own, opp):
                if r.get(own) is not None and r.get(opp) is not None:
                    pair[0].append(r[own] if is_home else r[opp]);pair[1].append(r[opp] if is_home else r[own])
            add((shots,shots_against),'hs','as');add((sots,sots_against),'hst','ast');add((corn,corn_against),'hc','ac')
            add((fouls,fouls_against),'hf','af');add((yellow,yellow_against),'hy','ay')
            if r.get('posh') is not None and r.get('posa') is not None:
                pos.append(r['posh'] if is_home else r['posa']);pos_against.append(r['posa'] if is_home else r['posh'])
            if r.get('shots_off') is not None and r.get('shots_off_away') is not None:
                soff.append(r['shots_off'] if is_home else r['shots_off_away']);soff_against.append(r['shots_off_away'] if is_home else r['shots_off'])
            if r.get('blocked') is not None and r.get('blocked_away') is not None:
                blocked.append(r['blocked'] if is_home else r['blocked_away']);blocked_against.append(r['blocked_away'] if is_home else r['blocked'])
        # xG has its own provider-quality flag and must not disappear just because
        # one unrelated core stat (for example cards) is unavailable. This was the
        # reason strong teams could be flattened in the 1X2 model.
        if r.get('xgh') is not None and r.get('xga') is not None:
            ownx=r['xgh'] if is_home else r['xga']; oppx=r['xga'] if is_home else r['xgh']
            xgs.append(ownx);xgs_against.append(oppx)
            if is_home:home_xg.append(ownx);home_xga.append(oppx)
            else:away_xg.append(ownx);away_xga.append(oppx)
        else:
            # Fallback for machines/providers where SofaScore xG is unavailable.
            # The value is an estimate from shots/SoT and is exposed as such.
            own_shots=r.get('hs') if is_home else r.get('as')
            own_sot=r.get('hst') if is_home else r.get('ast')
            opp_shots=r.get('as') if is_home else r.get('hs')
            opp_sot=r.get('ast') if is_home else r.get('hst')
            own_est=estimate_xg_from_shots(own_shots,own_sot)
            opp_est=estimate_xg_from_shots(opp_shots,opp_sot)
            if own_est is not None and opp_est is not None:
                xgs.append(own_est);xgs_against.append(opp_est)
                if is_home:home_xg.append(own_est);home_xga.append(opp_est)
                else:away_xg.append(own_est);away_xga.append(opp_est)
    avg=lambda a:_wavg(a) if a else None
    return {
        'matches':len(rs),'gf':avg(gf),'ga':avg(ga),
        'home_gf':avg(home_gf) if home_gf else avg(gf),'home_ga':avg(home_ga) if home_ga else avg(ga),
        'away_gf':avg(away_gf) if away_gf else avg(gf),'away_ga':avg(away_ga) if away_ga else avg(ga),
        'form':sum(pts)/(3*len(pts)) if pts else .5,
        'shots':avg(shots),'sot':avg(sots),'corners':avg(corn),'fouls':avg(fouls),'yellow':avg(yellow),
        'shots_against':avg(shots_against),'sot_against':avg(sots_against),'corners_against':avg(corn_against),
        'fouls_against':avg(fouls_against),'yellow_against':avg(yellow_against),'possession':avg(pos),'possession_against':avg(pos_against),'shots_off':avg(soff),'shots_off_against':avg(soff_against),'blocked':avg(blocked),'blocked_against':avg(blocked_against),
        'xg':avg(xgs),'xg_against':avg(xgs_against),
        'home_xg':avg(home_xg) if home_xg else avg(xgs),'home_xga':avg(home_xga) if home_xga else avg(xgs_against),
        'away_xg':avg(away_xg) if away_xg else avg(xgs),'away_xga':avg(away_xga) if away_xga else avg(xgs_against),
        'xg_matches':len(xgs),'verified_matches':verified,
        'xg_verified_matches':sum(1 for r in rs if r.get('xgh') is not None and r.get('xga') is not None),
        'xg_source':'SofaScore' if all(r.get('xgh') is not None and r.get('xga') is not None for r in rs if r.get('hs') is not None and r.get('hst') is not None) and any(r.get('xgh') is not None and r.get('xga') is not None for r in rs) else ('Misto' if any(r.get('xgh') is not None and r.get('xga') is not None for r in rs) else 'Stima da tiri/porta')
    }

def league_avgs(d):
    rs=current(d) or played(d)
    if not rs:return 1.35,1.10
    return sum(r['hg'] for r in rs)/len(rs),sum(r['ag'] for r in rs)/len(rs)

def league_stat_avgs(d):
    rs=[r for r in current(d) if stats_verified(r)]
    if not rs:return {'home_shots':13.0,'away_shots':11.0,'home_sot':4.5,'away_sot':3.8,'home_xg':1.45,'away_xg':1.15}
    def av(k,default):
        z=[r[k] for r in rs if r.get(k) is not None]
        return sum(z)/len(z) if z else default
    return {'home_shots':av('hs',13.0),'away_shots':av('as',11.0),'home_sot':av('hst',4.5),'away_sot':av('ast',3.8),
            'home_xg':av('xgh',1.45),'away_xg':av('xga',1.15)}

def team_strength_score(d,t):
    """Compact current-strength prior used to stop the xG proxy from flattening
    obvious team-quality differences early in a season. It is deliberately based
    on several independent signals and bounded before it can affect lambdas."""
    p=team_profile(d,t)
    vals=[]
    if p.get('xg') is not None and p.get('xg_against') is not None:
        vals.append(0.42*(p['xg']-p['xg_against']))
    if p.get('gf') is not None and p.get('ga') is not None:
        vals.append(0.25*(p['gf']-p['ga']))
    if p.get('shots') is not None and p.get('shots_against') is not None:
        vals.append(0.20*((p['shots']-p['shots_against'])/10.0))
    if p.get('sot') is not None and p.get('sot_against') is not None:
        vals.append(0.10*((p['sot']-p['sot_against'])/5.0))
    if p.get('form') is not None:
        vals.append(0.03*(p['form']-0.5))
    return max(-1.0,min(1.0,sum(vals))) if vals else 0.0

def xg(d,h,a):
    """Pre-match expected goals from venue-specific REAL xG, with goals and shot
    production as secondary priors.  Attack and defence are modelled separately
    so a strong team cannot be flattened into the opponent's average merely
    because the season sample is still small.
    """
    lh,la=league_avgs(d);sa=league_stat_avgs(d)
    hp=team_profile(d,h);ap=team_profile(d,a)

    # League baselines for the opponent-side defensive ratios.
    home_shots_against=sa['away_shots']; away_shots_against=sa['home_shots']
    home_sot_against=sa['away_sot']; away_sot_against=sa['home_sot']

    def venue_value(profile, venue, own, overall, fallback):
        v=profile.get(venue+'_'+own)
        if v is None:v=profile.get(overall)
        return fallback if v is None else v

    def strength(profile, venue, league_xg, league_goals, league_shots, league_sot, attack=True):
        if attack:
            x=venue_value(profile,venue,'xg','xg',league_xg)
            g=venue_value(profile,venue,'gf','gf',league_goals)
            sh=profile.get('shots')
            st=profile.get('sot')
            ratios=[x/max(league_xg,.15),g/max(league_goals,.15)]
            if sh is not None:ratios.append(sh/max(league_shots,.1))
            if st is not None:ratios.append(st/max(league_sot,.1))
        else:
            x=venue_value(profile,venue,'xga','xg_against',league_xg)
            g=venue_value(profile,venue,'ga','ga',league_goals)
            sh=profile.get('shots_against')
            st=profile.get('sot_against')
            ratios=[x/max(league_xg,.15),g/max(league_goals,.15)]
            if sh is not None:ratios.append(sh/max(league_shots,.1))
            if st is not None:ratios.append(st/max(league_sot,.1))
        # xG is deliberately the dominant signal; goals are a prior and shots/SoT
        # provide additional evidence rather than replacing xG.
        if len(ratios)>=4:
            return .55*ratios[0]+.20*ratios[1]+.15*ratios[2]+.10*ratios[3]
        return .70*ratios[0]+.20*ratios[1]+.10*sum(ratios[2:])/max(1,len(ratios[2:]))

    # Use current-season venue xG where there is a usable sample. With only a
    # couple of matches, blend toward the team's broader historical profile.
    def sample_weight(profile, venue):
        n=profile.get('xg_matches',0)
        # overall verified xG is a safer sample-size proxy than pretending we have
        # a large venue-specific xG sample.
        return min(1.0, 0.45 + 0.10*min(n,5))

    home_attack=strength(hp,'home',sa['home_xg'],lh,sa['home_shots'],sa['home_sot'],True)
    away_def=strength(ap,'away',sa['away_xg'],la,away_shots_against,away_sot_against,False)
    away_attack=strength(ap,'away',sa['away_xg'],la,sa['away_shots'],sa['away_sot'],True)
    home_def=strength(hp,'home',sa['home_xg'],lh,home_shots_against,home_sot_against,False)

    # Independent attack × opponent-defence construction.
    raw_h=sa['home_xg']*home_attack*away_def
    raw_a=sa['away_xg']*away_attack*home_def