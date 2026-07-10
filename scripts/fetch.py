"""Fetch SCA competitive-intelligence sources and return only new items.

Sources: ClinicalTrials.gov API v2, PubMed E-utilities, Google News RSS.
State is kept in data/seen.json so each run surfaces only genuinely new items.
On the very first run (no seen.json) everything is recorded as a silent
baseline and no items are returned as "new".
"""

import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEEN_FILE = DATA / "seen.json"

UA = {"User-Agent": "sca-iq-monitor/1.0 (competitive intelligence dashboard)"}

# News queries: targeted at competitors / the company to keep noise low.
NEWS_QUERIES = [
    "Stemchymal OR Steminent spinocerebellar",
    "Biohaven troriluzole spinocerebellar ataxia",
    "Vico Therapeutics VO659",
    "spinocerebellar ataxia therapy trial",
]


def _get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - network flakiness, retry
            last = e
            time.sleep(2 * (i + 1))
    raise last


def fetch_trials():
    fields = ",".join([
        "NCTId", "BriefTitle", "OverallStatus", "Phase",
        "LeadSponsorName", "LastUpdatePostDate", "InterventionName",
        "StudyType", "StartDate",
    ])
    url = ("https://clinicaltrials.gov/api/v2/studies"
           "?query.cond=spinocerebellar+ataxia"
           "&sort=LastUpdatePostDate:desc&pageSize=40"
           f"&fields={fields}")
    data = json.loads(_get(url))
    out = []
    for s in data.get("studies", []):
        p = s.get("protocolSection", {})
        idm = p.get("identificationModule", {})
        st = p.get("statusModule", {})
        des = p.get("designModule", {})
        spon = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
        arms = p.get("armsInterventionsModule", {})
        interventions = [i.get("name") for i in arms.get("interventions", []) if i.get("name")]
        out.append({
            "nctId": idm.get("nctId"),
            "title": idm.get("briefTitle"),
            "status": st.get("overallStatus"),
            "lastUpdate": st.get("lastUpdatePostDateStruct", {}).get("date"),
            "phase": ", ".join(des.get("phases", []) or []),
            "sponsor": spon.get("name"),
            "interventions": interventions,
            "url": f"https://clinicaltrials.gov/study/{idm.get('nctId')}",
        })
    return [t for t in out if t["nctId"]]


def fetch_papers():
    term = "spinocerebellar ataxia AND (therapy OR treatment OR trial OR clinical)"
    u = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed"
         f"&term={urllib.parse.quote(term)}"
         "&reldate=30&datetype=pdat&retmax=15&retmode=json&sort=date")
    ids = json.loads(_get(u)).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    u2 = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed"
          f"&id={','.join(ids)}&retmode=json")
    res = json.loads(_get(u2)).get("result", {})
    out = []
    for pid in ids:
        it = res.get(pid, {})
        if not it:
            continue
        src = it.get("fulljournalname") or it.get("source") or ""
        out.append({
            "pmid": pid,
            "title": it.get("title", "").rstrip("."),
            "pubdate": it.get("pubdate"),
            "journal": src,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
        })
    return out


def fetch_news():
    out = []
    seen_links = set()
    for q in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q="
               f"{urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en")
        try:
            root = ET.fromstring(_get(url))
        except Exception:  # noqa: BLE001 - skip a bad feed, keep the rest
            continue
        for item in root.iter("item"):
            link = item.findtext("link") or item.findtext("guid") or ""
            title = (item.findtext("title") or "").strip()
            if not link or link in seen_links or not title:
                continue
            seen_links.add(link)
            out.append({
                "title": title,
                "url": link,
                "pubdate": item.findtext("pubDate"),
                "source": (item.find("source").text if item.find("source") is not None else ""),
                "query": q,
            })
    return out


def load_seen():
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    return None


def save_seen(seen):
    DATA.mkdir(exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    trials = fetch_trials()
    papers = fetch_papers()
    news = fetch_news()

    seen = load_seen()
    baseline = seen is None
    if baseline:
        seen = {"trials": {}, "pmids": [], "news": []}

    new_trials, new_papers, new_news = [], [], []
    for t in trials:
        prev = seen["trials"].get(t["nctId"])
        if prev != t["lastUpdate"]:  # new trial or a fresh update
            if not baseline:
                new_trials.append(t)
            seen["trials"][t["nctId"]] = t["lastUpdate"]
    for p in papers:
        if p["pmid"] not in seen["pmids"]:
            if not baseline:
                new_papers.append(p)
            seen["pmids"].append(p["pmid"])
    for n in news:
        if n["url"] not in seen["news"]:
            if not baseline:
                new_news.append(n)
            seen["news"].append(n["url"])

    # keep state files from growing without bound
    seen["pmids"] = seen["pmids"][-500:]
    seen["news"] = seen["news"][-500:]

    save_seen(seen)
    return {
        "baseline": baseline,
        "trials": new_trials,
        "papers": new_papers,
        "news": new_news,
        "counts": {"trials": len(trials), "papers": len(papers), "news": len(news)},
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
