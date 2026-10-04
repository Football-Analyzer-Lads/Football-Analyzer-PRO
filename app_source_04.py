    else:start=late=0.0
    if market.startswith('H1') or market.startswith('H2'):
        suffix=market[2:]
        period='first' if market.startswith('H1') else 'second'
        if suffix.startswith(('O','U')) and suffix[1:].replace('.5','').isdigit():
            line=float(suffix[1:]);lam=0
            if hc.get('available'):
                hh,aa=hc['home'],hc['away']
                if period=='first':lam=((hh.get('first_xg') or hh.get('first_gf') or 0)+(aa.get('first_xga') or aa.get('first_ga') or 0)+(aa.get('first_xg') or aa.get('first_gf') or 0)+(hh.get('first_xga') or hh.get('first_ga') or 0))/2
                else:lam=((hh.get('second_xg') or hh.get('second_gf') or 0)+(aa.get('second_xga') or aa.get('second_ga') or 0)+(aa.get('second_xg') or aa.get('second_gf') or 0)+(hh.get('second_xga') or hh.get('second_ga') or 0))/2
            base=lam-line
            return z(base,.9) if suffix.startswith('O') else z(-base,.9)
        m=re.match(r'(?:H1|H2)(TS|SOT)_(O|U)(\d+\.5)',market)
        if m and hc.get('available'):
            kind,dir_,ln=m.groups();line=float(ln);hh,aa=hc['home'],hc['away'];pre='first_' if period=='first' else 'second_'
            if kind=='TS':
                hmean=(.58*hh.get(pre+'shots')+.42*aa.get(pre+'shots_against')) if hh.get(pre+'shots') is not None and aa.get(pre+'shots_against') is not None else None
                amean=(.58*aa.get(pre+'shots')+.42*hh.get(pre+'shots_against')) if aa.get(pre+'shots') is not None and hh.get(pre+'shots_against') is not None else None
            else:
                hmean=(.58*hh.get(pre+'sot')+.42*aa.get(pre+'sot_against')) if hh.get(pre+'sot') is not None and aa.get(pre+'sot_against') is not None else None
                amean=(.58*aa.get(pre+'sot')+.42*hh.get(pre+'sot_against')) if aa.get(pre+'sot') is not None and hh.get(pre+'sot_against') is not None else None
            mean=(hmean+amean) if hmean is not None and amean is not None else None
            if mean is not None:return z(mean-line,.9) if dir_=='O' else z(line-mean,.9)
    if market in ('1','1X'):
        return .45*z(diff,1.0)+.20*z(hp['home_xg']-ap['away_xga'] if hp.get('home_xg') is not None and ap.get('away_xga') is not None else diff,.9)+.15*z((hp.get('home_sot') or hp.get('sot') or 0)-(ap.get('away_sot_against') or ap.get('sot_against') or 0),2)+.20*formdiff
    if market in ('2','X2'):
        return -.45*z(diff,1.0)+.20*z((ap.get('away_xg') or xa)-(hp.get('home_xga') or xh),.9)+.15*z((ap.get('away_sot') or ap.get('sot') or 0)-(hp.get('home_sot_against') or hp.get('sot_against') or 0),2)-.20*formdiff
    if market=='12': return z(.58-p.get('X',0),.28)
    if market.startswith('O') and market[1:].replace('.5','').isdigit():
        line=float(market[1:]);return z(total-(line+.05),.9)*.55+z(((hp.get('xg') or 0)+(ap.get('xg') or 0))-2.5,1.5)*.25+z((late-start),1.0)*.20
    if market.startswith('U') and market[1:].replace('.5','').isdigit():
        line=float(market[1:]);return z((line+.05)-total,.9)*.55+z(2.5-((hp.get('xg') or 0)+(ap.get('xg') or 0)),1.5)*.25+z((start-late),1.0)*.20
    if market=='GG':
        return .55*z(min(xh,xa)-.55,.65)+.25*z((hp.get('xg') or xh)-.6,.7)+.20*z((ap.get('xg') or xa)-.6,.7)
    if market=='NG':
        return .55*z(.55-min(xh,xa),.65)+.25*z(.7-(hp.get('xg') or xh),.7)+.20*z(.7-(ap.get('xg') or xa),.7)
    if market.startswith('MG'):
        m=re.match(r'MG(?:H|A)?(\d+)-(\d+)',market)
        if m:
            lo,hi=map(int,m.groups());center=(lo+hi)/2
            return z(1-abs(total-center)/2.0,.7)
    if '+' in market:
        a,b=market.split('+',1);return .5*market_signal_score(d,r,p,a)+.5*market_signal_score(d,r,p,b)
    return 0.0

def _poisson_tail_over(lam, line):
    """P(total shots/corners > line) for a half-goal line."""
    threshold=int(math.floor(line))+1
    if lam <= 0:return 0.0
    return sum(pois(k,lam) for k in range(threshold, 80))

def _count_market_prob(lam, line, over=True):
    over_p=_poisson_tail_over(lam,line)
    return over_p if over else 1-over_p

def _expected_volume(d,r,kind):
    """Expected pre-match volume from recent venue splits + opponent concession.

    We deliberately use only the requested volume statistics here: shots, shots on
    target and corners. Profiles are recency-weighted, so the last matches matter
    more without letting one match dominate the estimate.
    """
    hp=team_profile(d,r['home'],venue='home'); ap=team_profile(d,r['away'],venue='away')
    # Early in a season one side may not yet have enough venue-specific matches.
    # Fall back to the all-venue recency profile rather than synthetic defaults.
    if hp.get('matches',0)<2: hp=team_profile(d,r['home'],venue='all')
    if ap.get('matches',0)<2: ap=team_profile(d,r['away'],venue='all')
    if kind=='shots':
        own_h,opp_h=hp.get('shots'),ap.get('shots_against')
        own_a,opp_a=ap.get('shots'),hp.get('shots_against')
        default_h,default_a=13.0,11.0
    elif kind=='sot':
        own_h,opp_h=hp.get('sot'),ap.get('sot_against')
        own_a,opp_a=ap.get('sot'),hp.get('sot_against')
        default_h,default_a=4.5,3.8
    elif kind=='corners':
        own_h,opp_h=hp.get('corners'),ap.get('corners_against')
        own_a,opp_a=ap.get('corners'),hp.get('corners_against')
        default_h,default_a=5.0,4.2
    else:
        raise ValueError(kind)
    h=0.58*own_h+0.42*opp_h if own_h is not None and opp_h is not None else (own_h or opp_h or default_h)
    a=0.58*own_a+0.42*opp_a if own_a is not None and opp_a is not None else (own_a or opp_a or default_a)
    return max(.5,h),max(.5,a),hp,ap

def volume_markets(d,r):
    """Build shot/corner markets for BEST.

    Keys are internal and intentionally separate from goal markets:
      TS_* total shots, HS_* home shots, AS_* away shots
      SOT_* total shots on target, HSOT_* home SoT, ASOT_* away SoT
      C_* total corners, HC_* home corners, AC_* away corners
    """
    out={}
    specs=[('shots','TS',1.0),('sot','SOT',1.0),('corners','C',1.0)]
    for kind,prefix,_ in specs:
        eh,ea,_,_= _expected_volume(d,r,kind)
        total=eh+ea
        if kind=='shots':
            lines=range(max(8,int(total)-6),min(31,int(total)+7))
            hprefix,aprefix='HS','AS'
        elif kind=='sot':
            lines=range(max(2,int(total)-4),min(15,int(total)+5))
            hprefix,aprefix='HSOT','ASOT'
        else:
            lines=range(max(4,int(total)-4),min(18,int(total)+5))
            hprefix,aprefix='HC','AC'
        for n in lines:
            line=n+0.5
            out[f'{prefix}_O{line:.1f}']=_count_market_prob(total,line,True)
            out[f'{prefix}_U{line:.1f}']=_count_market_prob(total,line,False)
            out[f'{hprefix}_O{line:.1f}']=_count_market_prob(eh,line,True)
            out[f'{hprefix}_U{line:.1f}']=_count_market_prob(eh,line,False)
            out[f'{aprefix}_O{line:.1f}']=_count_market_prob(ea,line,True)
            out[f'{aprefix}_U{line:.1f}']=_count_market_prob(ea,line,False)
    return out

def market_display_label(market):
    if market.startswith('MGH'):return 'Multigol casa '+market[3:]
    if market.startswith('MGA'):return 'Multigol trasferta '+market[3:]
    if market.startswith('MG'):return 'Multigol totale '+market[2:]
    labels={'1':'Casa','X':'Pareggio','2':'Trasferta','1X':'1X','X2':'X2','12':'12','GG':'Goal/Goal','NG':'No Goal','O1.5':'Over 1.5','O2.5':'Over 2.5','O3.5':'Over 3.5','U2.5':'Under 2.5','U3.5':'Under 3.5'}
    return labels.get(market,market)

def _volume_market_info(d,r,market):
    vm=volume_markets(d,r)
    prob=vm.get(market)
    if prob is None:return None
    m=re.match(r'^(TS|SOT|C|HS|AS|HSOT|ASOT|HC|AC)_[OU](\d+\.5)$',market)
    if not m:return None
    prefix, line=m.group(1),float(m.group(2))
    eh,ea,_,_= _expected_volume(d,r,'shots' if prefix in ('TS','HS','AS') else 'sot' if prefix in ('SOT','HSOT','ASOT') else 'corners')
    mean=eh+ea if prefix in ('TS','SOT','C') else eh if prefix in ('HS','HSOT','HC') else ea
    over='_O' in market
    margin=(mean-line) if over else (line-mean)
    return {'prob':prob,'mean':mean,'line':line,'margin':margin,'kind':'shots' if prefix in ('TS','HS','AS') else 'sot' if prefix in ('SOT','HSOT','ASOT') else 'corners'}

def best_engine(d,r,p,odds=None):
    """Choose the BEST from the user's four requested market families.

    BEST is intentionally independent of bookmaker availability. A real quote is
    used for value when available, but missing odds never produce NO BET.

    Allowed BEST families:
      - GG / NG
      - Over 2.5
      - Total shots
      - Shots on target (total/home/away)
    """
    odds=odds or {}
    ranked=[]
    halfctx=half_context_for_match(r)

    allowed=['GG','NG','O2.5']
    allowed += [k for k in p if re.match(r'^(TS|SOT|HS|AS|HSOT|ASOT)_[OU]\d+\.5$',k)]

    qlevel=data_quality(d,r['home'],r['away']).get('level','limited')
    quality_score={'high':1.0,'medium':.72,'limited':.45}.get(qlevel,.45)

    for market in allowed:
        if market not in p: continue
        try: prob=float(p[market])
        except Exception: continue
        if prob<=0 or prob>=.94: continue

        # Prefer the user's target probability band, but never require it.
        band_score=max(0.0,1.0-abs(prob-.80)/.20)

        real=odds.get(market)
        try: price=float(real) if real is not None else None
        except Exception: price=None

        implied=(1/price) if price and price>1 else None
        edge=(prob-implied) if implied is not None else 0.0

        vm=_volume_market_info(d,r,market)
        mean=margin=kind=None
        if vm:
            mean,margin,kind=vm['mean'],vm['margin'],vm['kind']
            labels={'shots':'Tiri','sot':'SoT'}
            prefix=market.split('_',1)[0]
            direction='Over' if '_O' in market else 'Under'
            line=re.search(r'[OU](\d+\.5)$',market).group(1)
            label_base=labels[kind]
            if prefix in ('HS','HSOT'): label_base+=' CASA'
            elif prefix in ('AS','ASOT'): label_base+=' TRASFERTA'
            label=f'{label_base} {direction} {line}'
        else:
            label=market_display_label(market)

        # Model-only markets are valid BEST picks. Real odds add value, but are
        # not a prerequisite. Slightly reward coherent data quality and, when
        # available, positive market edge.
        edge_score=max(0.0,min(1.0,(edge+.05)/.15)) if price else .50
        score=.72*band_score+.15*quality_score+.13*edge_score

        ranked.append({
            'market':market,
            'prob':round(prob*100,1),
            'fair':round(1/prob,2),
            'odd':round(price,2) if price else None,
            'implied':round(implied*100,1) if implied else None,
            'edge':round(edge*100,1) if price else None,
            'score':round(score,4),
            'confidence':round(min(.94,max(.50,prob*(.75+.25*quality_score)))*100,1),
            'mean':round(mean,2) if mean is not None else None,
            'margin':round(margin,2) if margin is not None else None,
            'kind':kind,
            'label':label,
            'quote_source':'bookmaker' if price else 'model'
        })

    ranked.sort(key=lambda x:(x['score'],x['prob']),reverse=True)
    return (ranked[0] if ranked else None),ranked

def shots_analysis(d,r,odds=None):
    """Always-on volume analysis without the old Under-selection bias.

    The direction is selected from probability + proximity to the projected mean
    + league baseline + real quote value when available. Labels explicitly say
    TOTAL/CASA/TRASFERTA so SoT can never be confused.
    """
    odds=odds or {};vm=volume_markets(d,r);items=[]
    league=league_stat_avgs(d)
    baselines={'TS':(league['home_shots']+league['away_shots']),'SOT':(league['home_sot']+league['away_sot'])}
    targets=[('TS','Tiri TOTALI'),('SOT','SoT TOTALI'),('HS','Tiri CASA'),('AS','Tiri TRASFERTA'),('HSOT','SoT CASA'),('ASOT','SoT TRASFERTA')]
    for prefix,label in targets:
        cand=[]
        for market,prob in vm.items():
            if not market.startswith(prefix+'_'):continue
            try:pr=float(prob)
            except:continue
            if not .68<=pr<=.84:continue
            info=_volume_market_info(d,r,market) or {};mean=info.get('mean');line=info.get('line')
            if mean is None or line is None:continue
            direction='Over' if '_O' in market else 'Under'
            # Prefer lines that are playable, not the most extreme tail. This is
            # symmetrical: Over and Under compete on equal footing.
            proximity=max(0,1-abs(mean-line)/max(5.0,mean*.45))
            base=baselines.get('TS' if prefix in ('TS','HS','AS') else 'SOT',None)
            baseline_signal=0 if base is None else max(-1,min(1,(mean-base)/max(2.0,base*.18)))
            direction_coherence=baseline_signal if direction=='Over' else -baseline_signal
            q=odds.get(market);edge=0
            if q and q>1:edge=pr-(1/float(q))
            score=.48*(1-abs(pr-.78)/.10)+.24*proximity+.18*((direction_coherence+1)/2)+.10*max(0,min(1,(edge+.02)/.12))
            cand.append((score,market,pr,info,q,edge))
        if not cand:continue
        _,market,pr,info,q,edge=max(cand,key=lambda x:x[0])
        direction='Over' if '_O' in market else 'Under'
        items.append({'market':market,'label':label,'direction':direction,'line':info.get('line'),'prob':round(pr*100,1),'odd':q,'fair':round(1/pr,2),'mean':info.get('mean'),'edge':round(edge*100,1) if q else None})
    return items


def scenario_reasons(d,r,best):
    hp=team_profile(d,r['home']);ap=team_profile(d,r['away']);xh,xa=xg(d,r['home'],r['away'])
    reasons=[]
    if hp.get('home_xg') is not None:reasons.append(f"{r['home']} xGF casa {hp['home_xg']:.2f}")
    if hp.get('home_xga') is not None:reasons.append(f"{r['home']} xGA casa {hp['home_xga']:.2f}")
    if ap.get('away_xg') is not None:reasons.append(f"{r['away']} xGF trasferta {ap['away_xg']:.2f}")
    if ap.get('away_xga') is not None:reasons.append(f"{r['away']} xGA trasferta {ap['away_xga']:.2f}")
    if hp.get('shots') is not None and ap.get('shots') is not None:reasons.append(f"tiri medi {hp['shots']:.1f}-{ap['shots']:.1f}")
    if hp.get('sot') is not None and ap.get('sot') is not None:reasons.append(f"SoT medi {hp['sot']:.1f}-{ap['sot']:.1f}")
    reasons.append(f"xG previsto {xh:.2f}-{xa:.2f}")
    hc=half_context_for_match(r)
    if hc.get('available'):
        hh,aa=hc['home'],hc['away']
        reasons.append(f"1° tempo: {r['home']} GF {hh.get('first_gf',0):.2f} / xG {hh.get('first_xg',0) or 0:.2f} · {r['away']} GF {aa.get('first_gf',0):.2f} / xG {aa.get('first_xg',0) or 0:.2f}")
        reasons.append(f"2° tempo: {r['home']} GF {hh.get('second_gf',0):.2f} / xG {hh.get('second_xg',0) or 0:.2f} · {r['away']} GF {aa.get('second_gf',0):.2f} / xG {aa.get('second_xg',0) or 0:.2f}")
        reasons.append(f"Start index: {hh.get('start_index',0):+.2f} vs {aa.get('start_index',0):+.2f} · campione {hc.get('sample',0)} partite")
    if best:reasons.append(f"scenario BEST: {best['market']} · probabilità {best['prob']:.1f}% · quota {best['odd']:.2f} · value {best['edge']:+.1f}%")
    return reasons

def coupon_candidates(p,odds=None,lo=0.75,hi=0.85,ranked=None):
    odds=odds or {};items=[]
    # Only candidates that pass the scenario engine are allowed into the standard coupon.
    allowed={x['market']:x for x in (ranked or []) if x.get('score',0)>=0.52 and x.get('edge',0)>=0}
    for market,prob in p.items():
        if market not in allowed or not(lo<=prob<=hi):continue
        odd=odds.get(market);implied=(1/odd) if odd and odd>1 else None;edge=(prob-implied) if implied is not None else None
        rank=allowed[market]
        items.append({'market':market,'prob':round(prob*100,1),'fair':round(1/prob,2),'odd':odd,'implied':round(implied*100,1) if implied else None,'edge':round(edge*100,1) if edge is not None else None,'score':rank['score'],'signal':rank.get('signal',0)})
    return sorted(items,key=lambda x:(x['score'],x['signal']),reverse=True)

def data_quality(d,h,a):
    hp=team_profile(d,h);ap=team_profile(d,a);n=min(hp['matches'],ap['matches'])
    relevant=[r for r in current(d) if h in (r['home'],r['away']) or a in (r['home'],r['away'])]