import csv, io, json, math, os, re, statistics, time, subprocess
from datetime import datetime, date, timedelta
from urllib.request import Request, urlopen
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET
from flask import Flask, render_template, jsonify, request
from schedule import STATIC_SCHEDULE

BASE=os.path.dirname(__file__)
CACHE=os.path.join(BASE,'cache.json')
SOFA_CACHE=os.path.join(BASE,'sofa_cache.json')
URLS={
 '2026/27':'https://football-data.co.uk/mmz4281/2627/I1.csv',
 '2025/26':'https://football-data.co.uk/mmz4281/2526/I1.csv',
 '2024/25':'https://football-data.co.uk/mmz4281/2425/I1.csv',
}
FIX='https://football-data.co.uk/matches/resources/fixtures.csv'
SOFA='https://api.sofascore.com/api/v1'
API_FOOTBALL='https://v3.football.api-sports.io'
API_FOOTBALL_LEAGUE=135  # Serie A
ODDS_CACHE=os.path.join(BASE,'odds_cache.json')
CONTEXT_CACHE=os.path.join(BASE,'context_cache.json')
NEWS_CACHE=os.path.join(BASE,'news_cache.json')

def _local_config_value(name):
    value=os.environ.get(name,'').strip()
    if value:return value
    cfg=os.path.join(BASE,'config.env')
    try:
        for line in open(cfg,encoding='utf-8'):
            line=line.strip()
            if not line or line.startswith('#') or '=' not in line:continue
            k,v=line.split('=',1)
            if k.strip()==name:return v.strip().strip('\"').strip("'")
    except Exception:pass
    return ''

API_FOOTBALL_KEY=_local_config_value('API_FOOTBALL_KEY')
API_FOOTBALL_LAST_ERROR=''
API_FOOTBALL_LAST_STATUS={}
app=Flask(__name__, static_folder=os.path.join(BASE,'static'), template_folder=os.path.join(BASE,'templates'), static_url_path='/static')

TEAM_ALIASES={'Ssc Napoli':'Napoli','SS Monza 1912':'Monza','Inter Milan':'Inter','Internazionale':'Inter','Milan':'AC Milan','Roma':'AS Roma','Como 1907':'Como','Como Calcio':'Como','Frosinone Calcio':'Frosinone','Frosinone 1928':'Frosinone'}

def get(u):
    req=Request(u,headers={'User-Agent':'Mozilla/5.0 FootballAnalyzer/Final'})
    try:
        with urlopen(req,timeout=30) as resp:return resp.read()
    except Exception as first_error:
        # macOS fallback: use the system curl binary. This avoids Python SSL/TLS
        # or certificate differences between older Intel and newer Apple Silicon Macs.
        try:
            cp=subprocess.run(['curl','-fL','--max-time','35','-A','Mozilla/5.0 FootballAnalyzer/Final',u],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
            if cp.stdout:return cp.stdout
        except Exception:
            pass
        raise first_error

def http_json(url, timeout=15):
    return json.loads(get(url).decode('utf-8'))

def num(x):
    try:return float(x) if x not in (None,'') else None
    except:return None

def dt(x):
    if not x:return None
    x=x.strip()
    for f in ('%d/%m/%Y','%d/%m/%y','%Y-%m-%d'):
        try:return datetime.strptime(x,f).date().isoformat()
        except:pass
    return None

def norm_team(x):return TEAM_ALIASES.get(' '.join((x or '').strip().split()),' '.join((x or '').strip().split()))

def result_rows(data,season):
    out=[]
    for r in csv.DictReader(io.StringIO(data.decode('utf-8-sig','replace'))):
        d=dt(r.get('Date',''));h=norm_team(r.get('HomeTeam'));a=norm_team(r.get('AwayTeam'))
        if not d or not h or not a:continue
        out.append({'season':season,'date':d,'time':(r.get('Time') or '').strip(),'home':h,'away':a,'hg':num(r.get('FTHG')),'ag':num(r.get('FTAG')),
        'hs':num(r.get('HS')),'as':num(r.get('AS')),'hst':num(r.get('HST')),'ast':num(r.get('AST')),'hc':num(r.get('HC')),'ac':num(r.get('AC')),
        'hf':num(r.get('HF')),'af':num(r.get('AF')),'hy':num(r.get('HY')),'ay':num(r.get('AY')),
        'bh':num(r.get('B365H')),'bd':num(r.get('B365D')),'ba':num(r.get('B365A')),'bo':num(r.get('B365>2.5')),'bu':num(r.get('B365<2.5')),
        'bbh':num(r.get('PSH')),'bba':num(r.get('PSA'))})
    return out

def fixture_rows(data):
    out=[]
    for r in csv.DictReader(io.StringIO(data.decode('utf-8-sig','replace'))):
        d=dt(r.get('Date',''));h=norm_team(r.get('HomeTeam'));a=norm_team(r.get('AwayTeam'))
        if not d or not h or not a:continue
        out.append({'div':(r.get('Div') or '').strip().upper(),'date':d,'time':(r.get('Time') or '').strip(),'home':h,'away':a,'bh':num(r.get('B365H')),'bd':num(r.get('B365D')),'ba':num(r.get('B365A')),'bo':num(r.get('B365>2.5')),'bu':num(r.get('B365<2.5'))})
    return out

def _read_json(path):
    try:
        with open(path,encoding='utf-8') as f:return json.load(f)
    except Exception:return None

def _seed_cache():
    seed=os.path.join(BASE,'cache_seed.json')
    d=_read_json(seed)
    return d if isinstance(d,dict) and len(d.get('schedule',[]))==380 else None

def refresh(force_stats=False):
    # IMPORTANT: never replace a working cache with an empty cache just because
    # football-data/SofaScore is temporarily unreachable. This is especially
    # important on a new Mac where the first network/TLS request can fail.
    previous=_read_json(CACHE) or _seed_cache() or {}
    base_schedule=previous.get('schedule') if len(previous.get('schedule',[]))==380 else STATIC_SCHEDULE
    d={'updated':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
       'seasons':dict(previous.get('seasons',{})),
       'fixtures':list(previous.get('fixtures',[])),
       'schedule':base_schedule,
       'errors':[],
       'validation':previous.get('validation',{})}
    for s,u in URLS.items():
        try:
            rows=result_rows(get(u),s)
            # Accept a provider response only if it contains actual rows.
            # Otherwise retain the last known-good season data.
            if rows:
                d['seasons'][s]=rows
            else:
                d['errors'].append(f'{s}: provider returned 0 rows; previous data retained')
        except Exception as e:
            d['errors'].append(f'{s}: {e} (previous data retained)')
    try:
        fx=fixture_rows(get(FIX))
        if fx:d['fixtures']=fx
        else:d['errors'].append('fixtures: provider returned 0 rows; previous data retained')
    except Exception as e:d['errors'].append(f'fixtures: {e} (previous data retained)')
    # Merge any confirmed fixture date/time into the 380-match local calendar without changing its round mapping.
    fx={(x['home'],x['away']):x for x in d.get('fixtures',[]) if x.get('div')=='I1'}
    for r in d.get('schedule',[]):
        x=fx.get((r['home'],r['away']))
        if x:
            if x.get('date'):r['date']=x['date']
            if x.get('time'):r['time']=x['time']
    try: enrich_current_stats(d, force=force_stats)
    except Exception as e: d['errors'].append(f'stat enrichment: {e}')
    # Only write the cache after preserving/merging the last good dataset.
    # A temporary provider outage can therefore never turn Squadre into
    # 'Ultime 0'.
    with open(CACHE,'w',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False)
    return d


# ---- data validation / enrichment -------------------------------------------------
# Football-Data is retained for results and bookmaker prices. For the current season,
# detailed team match statistics are reconciled against SofaScore's public match data.
# The model never silently substitutes one provider's field for another provider's
# differently-defined field.
STAT_KEYS={
    # SofaScore stable machine keys. These are preferred over display names.
    'shots':['totalShotsOnGoal','totalShots','shots','total shots'],
    'sot':['shotsOnGoal','shotsOnTarget','shots on target'],
    'shots_off':['shotsOffGoal','shotsOffTarget','shots off target'],
    'blocked':['blockedScoringAttempt','blockedShots','blocked shots'],
    'corners':['cornerKicks','corners','corner kicks'],
    'fouls':['fouls','fouls committed'],
    'yellow':['yellowCards','yellow cards'],
    'possession':['ballPossession','possession'],
    'xg':['expectedGoals','expected goals','xg'],
}

# Display-name fallbacks kept for older/alternate SofaScore responses.
STAT_ALIASES=STAT_KEYS

def _stat_number(v):
    if v is None:return None
    if isinstance(v,(int,float)):return float(v)
    m=re.search(r'-?\d+(?:[\.,]\d+)?',str(v))
    return float(m.group(0).replace(',','.')) if m else None

def _norm_stat_name(x):
    return re.sub(r'[^a-z0-9]+',' ',str(x or '').lower()).strip()

def sofa_match_statistics(event_id, force=False):
    data=sofa_get(f'/event/{event_id}/statistics',ttl=12*3600,force=force)
    if not data:return None
    periods=data.get('statistics') or []
    period=next((x for x in periods if x.get('period')=='ALL'), periods[0] if periods else None)
    if not period:return None

    # Index by SofaScore's stable `key` first. The `name` field is a display label
    # and can vary; using it as the primary key was the reason xG/fouls/cards were
    # missing in earlier builds.
    by_key={}; by_name={}
    for g in period.get('groups',[]):
        for item in g.get('statisticsItems',[]):
            key=str(item.get('key') or '').strip()
            name=_norm_stat_name(item.get('name'))
            pair=(item.get('homeValue'),item.get('awayValue'))
            if pair[0] is None and pair[1] is None:
                pair=(item.get('home'),item.get('away'))
            if key: by_key[key]=pair
            if name: by_name[name]=pair

    def pick(keys):
        for wanted in keys:
            if wanted in by_key:return by_key[wanted]
        for wanted in keys:
            wanted=_norm_stat_name(wanted)
            if wanted in by_name:return by_name[wanted]
        return (None,None)

    out={}
    for field,keys in STAT_KEYS.items():
        h,a=pick(keys);out[field]=(_stat_number(h),_stat_number(a))
    return out

def enrich_current_stats(d, force=False):
    current=d.get('seasons',{}).get('2026/27',[])
    # Build one scheduled-event lookup per match date, so we do not repeatedly download the date feed.
    by_date={}
    changed=0;checked=0;errors=[]
    for r in current:
        if r.get('hg') is None or r.get('ag') is None:continue
        checked+=1;date_key=r['date']
        if date_key not in by_date:
            data=sofa_get('/sport/football/scheduled-events/'+date_key,ttl=6*3600,force=force)
            by_date[date_key]=data or {}
        ev=None
        for e in by_date[date_key].get('events',[]):
            if norm_team(e.get('homeTeam',{}).get('name'))==r['home'] and norm_team(e.get('awayTeam',{}).get('name'))==r['away']:
                ev=e;break
        if not ev:continue
        stats=sofa_match_statistics(ev.get('id'), force=force)
        if not stats:continue
        # Preserve provider provenance and replace ONLY with verified ALL-period values.
        r['stats_source']='SofaScore'
        r['sofa_event_id']=ev.get('id')
        field_map={
            'hs':('shots',0),'as':('shots',1),
            'hst':('sot',0),'ast':('sot',1),
            'hc':('corners',0),'ac':('corners',1),
            'shots_off_h':('shots_off',0),'shots_off_a':('shots_off',1),
            'blocked_h':('blocked',0),'blocked_a':('blocked',1),
            'hf':('fouls',0),'af':('fouls',1),
            'hy':('yellow',0),'ay':('yellow',1),
            'posh':('possession',0),'posa':('possession',1),
            'xgh':('xg',0),'xga':('xg',1),
        }
        for field,(src,side) in field_map.items():
            # Temporary *_h/*_a keys are stored below; normal fields replace Football-Data values.
            target=field
            if field=='shots_off_h': target='shots_off'
            elif field=='shots_off_a': target='shots_off_away'
            elif field=='blocked_h': target='blocked'
            elif field=='blocked_a': target='blocked_away'
            elif field=='posa': target='possession_away'
            pair=stats.get(src,(None,None));v=pair[side]
            if v is not None:
                if target in ('shots_off_away','blocked_away','possession_away'):
                    r[target]=v
                else:
                    if r.get(target)!=v: changed+=1
                    r[target]=v
        # Explicit verified aliases used by the model/data inspector.
        r['shots_off_home']=r.get('shots_off')
        r['shots_off_away']=r.get('shots_off_away')
        r['blocked_home']=r.get('blocked')
        r['blocked_away']=r.get('blocked_away')
        r['possession_home']=r.get('posh')
        r['possession_away']=r.get('possession_away')
        required=('hs','as','hst','ast','hc','ac','hf','af','hy','ay')
        # xG is provider-dependent; record it separately rather than downgrading
        # the whole match when SofaScore does not publish it.
        core_ok=all(r.get(k) is not None for k in required)
        r['data_quality']={'stats':'verified' if core_ok else 'partial','source':'SofaScore','event_id':ev.get('id'),'xg':'verified' if r.get('xgh') is not None and r.get('xga') is not None else 'unavailable'}
        if not core_ok:
            errors.append(f"{r['date']} {r['home']}-{r['away']}: incomplete SofaScore core stats")
    d['validation']={'version':7,'checked_current_matches':checked,'stat_fields_enriched':changed,'source':'SofaScore current-season match statistics + Football-Data results/odds','errors':errors,'forced_refresh':bool(force)}
    return d

def load():
    if os.path.exists(CACHE):
        try:
            d=json.load(open(CACHE,encoding='utf-8'))
            age=time.time()-os.path.getmtime(CACHE)
            # Rebuild old V8 caches once, then keep data fresh without requiring a manual refresh.
            if len(d.get('schedule',[]))==380 and d.get('validation',{}).get('version')==7 and age < 1200:
                return d
        except:pass
    return refresh()

def played(d):return [r for rs in d.get('seasons',{}).values() for r in rs if r.get('hg') is not None and r.get('ag') is not None]
def current(d):return [r for r in d.get('seasons',{}).get('2026/27',[]) if r.get('hg') is not None and r.get('ag') is not None]
def all_current(d):return d.get('seasons',{}).get('2026/27',[])
def teams(d):return sorted({x for r in d.get('schedule',[]) for x in (r['home'],r['away'])})
def upcoming(d):
    today=date.today().isoformat(); played_keys={(r['date'],r['home'],r['away']) for r in current(d)};out=[]
    for r in d['schedule']:
        k=(r['date'],r['home'],r['away'])
        if r['date']>=today and k not in played_keys:out.append(dict(r))
    for r in d.get('fixtures',[]):
        if r.get('div')=='I1' and r['date']>=today:
            rr=dict(r);k=(rr['date'],rr['home'],rr['away'])
            if k not in played_keys and not any(x['date']==rr['date'] and x['home']==rr['home'] and x['away']==rr['away'] for x in out):out.append(rr)
    return sorted(out,key=lambda x:(x['date'],x.get('time',''),x['home']))

def stats_verified(r):
    # Core match statistics are available directly from Football-Data (HS/AS,
    # HST/AST, HC/AC, HF/AF, HY/AY). SofaScore is preferred when enrichment is
    # available, but it must not be a prerequisite for showing these fields.
    core=('hs','as','hst','ast','hc','ac','hf','af','hy','ay')
    return all(r.get(k) is not None for k in core)

def estimate_xg_from_shots(shots, sot):
    """Transparent xG proxy used only when a real provider xG is unavailable.
    It is deliberately labelled as an estimate; it is never presented as
    SofaScore xG."""
    if shots is None or sot is None:
        return None
    shots=float(shots); sot=max(0.0,min(float(sot),shots))
    # On-target shots carry more information than shots off target. The small
    # coefficient on off-target attempts keeps the proxy conservative.
    value=0.16*sot + 0.025*(shots-sot)
    return round(max(0.05,min(4.5,value)),3)

def _wavg(values, half_life=35):
    """Recency-weighted average. Newest observation gets weight 1."""
    if not values:return None
    # values are already chronological; use exponential decay by observation index.
    weights=[math.exp(-math.log(2)*(len(values)-1-i)/max(half_life,1)) for i in range(len(values))]
    return sum(v*w for v,w in zip(values,weights))/sum(weights)

def _sofa_period_pair(data, period):
    """Read one SofaScore statistics period (1ST/2ND) using stable keys first."""
    periods=(data or {}).get('statistics') or []
    block=next((x for x in periods if str(x.get('period','')).upper()==period), None)
    if not block:return {}
    by_key={};by_name={}
    for g in block.get('groups',[]):
        for item in g.get('statisticsItems',[]):
            pair=(item.get('homeValue'),item.get('awayValue'))
            if pair[0] is None and pair[1] is None:pair=(item.get('home'),item.get('away'))
            key=str(item.get('key') or '').strip()
            name=_norm_stat_name(item.get('name'))
            if key:by_key[key]=pair
            if name:by_name[name]=pair
    out={}
    for field,keys in STAT_KEYS.items():
        pair=None
        for k in keys:
            if k in by_key:pair=by_key[k];break
        if pair is None:
            for k in keys:
                if _norm_stat_name(k) in by_name:pair=by_name[_norm_stat_name(k)];break
        if pair is not None:out[field]=(_stat_number(pair[0]),_stat_number(pair[1]))
    return out

def sofa_match_half_statistics(event_id, force=False):
    data=sofa_get(f'/event/{event_id}/statistics',ttl=12*3600,force=force)
    if not data:return None
    return {'1ST':_sofa_period_pair(data,'1ST'),'2ND':_sofa_period_pair(data,'2ND')}

def sofa_team_half_profile(team_id, venue='all', n=6):
    """Recent first/second-half behaviour for one team.

    This is deliberately based on finished recent matches and uses the venue split
    of the upcoming fixture. It captures whether a side starts fast/slow and whether
    its shot/xG activity changes after the interval.
    """
    if not team_id:return {'matches':0}
    cache=_context_cache_load();key=f'half_profile_{team_id}_{venue}_{n}';now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<6*3600:return v.get('data',{})
    try:data=sofa_get(f'/team/{team_id}/events/last/0',ttl=1800) or {}
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
    cache=_context_cache_load();key='season_fixtures_2026';now=time.time();v=cache.get(key)
    if v and now-v.get('ts',0)<6*3600:return v.get('data',[])
    data=api_football_get(f'/fixtures?league={API_FOOTBALL_LEAGUE}&season=2026',ttl=6*3600) or {}
    rows=data.get('response') or []
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