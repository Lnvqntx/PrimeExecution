from __future__ import annotations

import pandas as pd
from features import build_features, load_snapshots

def main():
    df = build_features(load_snapshots("data/ticker_snapshots.csv"))
    times = sorted(df.timestamp.unique())
    print("="*72)
    print("PRIME EXECUTION — V5 EDGE VALIDATION")
    print("="*72)
    print(f"Snapshots: {len(times)} | Pairs: {df.pair.nunique()}")
    for horizon in (15, 30, 60):
        vals=[]
        for i in range(len(times)-horizon):
            a=df[df.timestamp==times[i]][["pair","change_24h"]].dropna()
            b=df[df.timestamp==times[i+horizon]][["pair","last_price"]].dropna()
            c=df[df.timestamp==times[i]][["pair","last_price"]].dropna()
            x=a.merge(c,on="pair").merge(b,on="pair",suffixes=("_now","_future"))
            if len(x)<20: continue
            x["fwd"]=x.last_price_future/x.last_price_now-1
            x["signal"]=-x.change_24h
            top=x.nlargest(max(5,len(x)//10),"signal").fwd.mean()
            bottom=x.nsmallest(max(5,len(x)//10),"signal").fwd.mean()
            vals.append(top-bottom)
        s=pd.Series(vals)
        print(f"{horizon:>2}m contrarian top-bottom: mean={s.mean()*100:+.3f}% median={s.median()*100:+.3f}% samples={len(s)}")
    print("Positive spread after costs is the bar. Research only.")
if __name__=="__main__":
    main()
