import csv, io, json, math, os, re, statistics, time, subprocess, threading
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

_refresh_lock=threading.Lock()
_refresh_running=False

def _start_background_refresh(force_stats=False):
    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            return False
        _refresh_running=True

    def worker():
        global _refresh_running
        try:
            refresh(force_stats=force_stats)
        except Exception:
            pass
        finally:
            with _refresh_lock:
                _refresh_running=False

    threading.Thread(target=worker,daemon=True,name='football-analyzer-refresh').start()
    return True

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
    # Merge confirmed fixture date/time into the local calendar without changing round mapping.
    # Football-Data can lag on future Serie A dates. API-Football is already used by the
    # project for injuries/context, so use it as a second authoritative future-fixture
    # source when the local API key is configured. This prevents SofaScore lookups from
    # failing because a provisional/static date is off by one or more days.
    fx={(x['home'],x['away']):x for x in d.get('fixtures',[]) if x.get('div')=='I1'}
    for r in d.get('schedule',[]):
        x=fx.get((r['home'],r['away']))
        if x:
            if x.get('date'):r['date']=x['date']
            if x.get('time'):r['time']=x['time']

    # Second pass: current-season API-Football fixtures. Only overwrite date/time
    # when the same home/away pairing is found; never alter the round assignment.
    try:
        api_rows=api_football_season_fixtures() if API_FOOTBALL_KEY else []
        api_map={}
        for item in api_rows:
            teams=item.get('teams') or {}
            h=norm_team((teams.get('home') or {}).get('name'))
            a=norm_team((teams.get('away') or {}).get('name'))
            fd=item.get('fixture') or {}
            raw_date=fd.get('date')
            if not h or not a or not raw_date: continue
            try:
                z=datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                from zoneinfo import ZoneInfo
                z=z.astimezone(ZoneInfo('Europe/Rome'))
                api_map[(h,a)]={'date':z.date().isoformat(),'time':z.strftime('%H:%M')}
            except Exception:
                continue
        for r in d.get('schedule',[]):
            x=api_map.get((r['home'],r['away']))
            if x:
                r['date']=x['date']
                if x.get('time'): r['time']=x['time']
        # If the provider returned the full current Serie A season, rebuild the
        # calendar from real fixtures. Merely changing dates on an old 380-match
        # seed leaves relegated/promoted clubs (e.g. Venezia) in the new season.
        if len(api_rows)>=300:
            actual=[]
            for item in api_rows:
                teams=item.get('teams') or {};fixture=item.get('fixture') or {};league=item.get('league') or {}
                h=norm_team((teams.get('home') or {}).get('name',''))
                a=norm_team((teams.get('away') or {}).get('name',''))
                raw_date=fixture.get('date')
                if not h or not a or not raw_date:continue
                try:
                    z=datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                    from zoneinfo import ZoneInfo
                    z=z.astimezone(ZoneInfo('Europe/Rome'))
                except Exception:continue
                rnd=str(league.get('round') or '')
                m=re.search(r'(\\d+)\\s*    except Exception as e:
        d['errors'].append(f'api football fixtures merge: {e}')
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
    d['validation']={'version':8,'checked_current_matches':checked,'stat_fields_enriched':changed,'source':'SofaScore current-season match statistics + Football-Data results/odds','errors':errors,'forced_refresh':bool(force)}
    return d

def load():
    # NEVER block the web UI on a data refresh. If a valid cache exists, return it
    # immediately and refresh in the background when it is stale.
    try:
        d=json.load(open(CACHE,encoding='utf-8')) if os.path.exists(CACHE) else None
        if isinstance(d,dict) and len(d.get('schedule',[]))==380:
            age=time.time()-os.path.getmtime(CACHE)
            if age >= 1200 or d.get('validation',{}).get('version')!=8:
                _start_background_refresh(force_stats=False)
            return d
    except Exception:
        pass
    seed=_seed_cache()
    if seed:
        d={'updated':'','seasons':{},'fixtures':[],'schedule':seed,'errors':[],'validation':{}}
        try:
            with open(CACHE,'w',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False)
        except Exception:pass
        _start_background_refresh(force_stats=False)
        return d
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
    try:data=sofa_get(f'/team/{team_id}/events/last/0',ttl=1800) or {},rnd)
                if not m:continue
                actual.append({'date':z.date().isoformat(),'time':z.strftime('%H:%M'),
                               'home':h,'away':a,'round':int(m.group(1))})
            if len(actual)>=300:
                d['schedule']=sorted(actual,key=lambda x:(x['round'],x['date'],x['home']))
    except Exception as e:
        d['errors'].append(f'api football fixtures merge: {e}')
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
    d['validation']={'version':8,'checked_current_matches':checked,'stat_fields_enriched':changed,'source':'SofaScore current-season match statistics + Football-Data results/odds','errors':errors,'forced_refresh':bool(force)}
    return d

def load():
    # NEVER block the web UI on a data refresh. If a valid cache exists, return it
    # immediately and refresh in the background when it is stale.
    try:
        d=json.load(open(CACHE,encoding='utf-8')) if os.path.exists(CACHE) else None
        if isinstance(d,dict) and len(d.get('schedule',[]))==380:
            age=time.time()-os.path.getmtime(CACHE)
            if age >= 1200 or d.get('validation',{}).get('version')!=8:
                _start_background_refresh(force_stats=False)
            return d
    except Exception:
        pass
    seed=_seed_cache()
    if seed:
        d={'updated':'','seasons':{},'fixtures':[],'schedule':seed,'errors':[],'validation':{}}
        try:
            with open(CACHE,'w',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False)
        except Exception:pass
        _start_background_refresh(force_stats=False)
        return d
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