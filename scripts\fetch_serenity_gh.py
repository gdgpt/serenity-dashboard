#!/usr/bin/env python3
"""Fetch Serenity tweets via RSSHub, extract cashtags, save to SQLite."""
import datetime as dt, json, re, sqlite3, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "serenity.sqlite"
JSON_OUT = ROOT / "data" / "tweets_snapshot.json"
CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9.]{0,9})(?![A-Za-z0-9_])")
NOISE = {"AI","I","A","USD","US","CEO","ETF","IPO","SO","OR","IT","BE","AT","IN","ON","BY"}

URLS = [
    "https://rsshub.app/twitter/user/aleabitoreddit/readable=1&limit=50",
    "https://rsshub.pseudoyu.com/twitter/user/aleabitoreddit/readable=1&limit=50",
    "https://rsshub.rssforever.com/twitter/user/aleabitoreddit/readable=1&limit=50",
]

def fetch_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SerenityBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(5 * (i + 1))

data = None
for url in URLS:
    try:
        data = fetch_json(url)
        print(f"OK: {url}")
        break
    except Exception as e:
        print(f"FAIL: {url} -> {e}")

if not data:
    print("All mirrors failed")
    sys.exit(1)

items = data.get("items", [])
print(f"Got {len(items)} tweets")

DB.parent.mkdir(parents=True, exist_ok=True)
con = sqlite3.connect(DB)
con.executescript("""
    pragma journal_mode=wal;
    create table if not exists tweets(tweet_id text primary key,source text,author_screen_name text,created_at text,text text,url text,favorite_count integer,reply_count integer,retweet_count integer,quote_count integer,raw_json text);
    create table if not exists mentions(id integer primary key autoincrement,symbol text,tweet_id text references tweets(tweet_id) on delete cascade,mentioned_at text,text text,source text,unique(symbol,tweet_id));
    create table if not exists prices(symbol text,date text,close real,volume integer,primary key(symbol,date));
    create index if not exists idx_m on mentions(symbol,mentioned_at);
    create index if not exists idx_p on prices(symbol,date);
""")

new_tweets = 0
snapshot = []
for item in items:
    tid = item.get("id") or str(hash(item.get("title","")))
    title = item.get("title", "") or ""
    desc = item.get("description", "") or item.get("content_html", "") or ""
    text = f"{title}\n{desc}".strip()
    pub = item.get("date_published") or dt.datetime.now(dt.timezone.utc).isoformat()
    url = item.get("url", "")
    symbols = sorted(set(m.group(1).upper() for m in CASHTAG_RE.finditer(text) if m.group(1).upper() not in NOISE and 1 < len(m.group(1)) <= 10))
    raw = json.dumps(item, ensure_ascii=False)
    con.execute("insert or ignore into tweets values(?,?,?,?,?,?,?,?,?,?,?)",(tid,"rsshub","aleabitoreddit",pub,text[:2000],url,0,0,0,0,raw))
    if con.total_changes:
        new_tweets += 1
        for sym in symbols:
            con.execute("insert or ignore into mentions(symbol,tweet_id,mentioned_at,text,source) values(?,?,?,?,?)",(sym,tid,pub,text[:500],"rsshub"))
    snapshot.append({"id":tid,"date":pub,"text":text[:500],"symbols":symbols,"url":url})

con.commit(); con.close()
JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
JSON_OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"New: {new_tweets} tweets -> {DB}")
