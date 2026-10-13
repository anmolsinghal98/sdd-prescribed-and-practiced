# One-off: snapshot the PR layer out of MySQL into the package, so the claims
# can be checked without it. The per-tool PR tables are the only part of the
# corpus the SQLite export does not carry.
import os, json, collections
for line in open("/data2/shyamaga/AndrewSDD@JSS/.env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
import mysql.connector
TOOLS = ["agent_os", "claude_code", "codex", "conductor", "cursor", "moai",
         "opencode", "openspec", "speckit", "specweave", "trae"]
c = mysql.connector.connect(host="localhost", port=3306, user=os.environ["myDB_user"],
                            password=os.environ["myDB_pwd"], database="specdriven")
cur = c.cursor()
pr, repos, queued, rows = {}, set(), 0, 0
for t in TOOLS:
    cur.execute(f"SELECT repo_name, pr_number, touches_code, is_merged, state FROM {t}_prs")
    for r, n, tc, m, st in cur.fetchall():
        rows += 1
        k = f"{r}#{n}"
        p = pr.setdefault(k, {"code": 0, "merged": 0, "state": st, "tools": []})
        p["code"] = p["code"] or int(tc or 0)
        p["merged"] = p["merged"] or int(m or 0)
        p["tools"].append(t)
    cur.execute(f"SELECT COUNT(*) FROM {t}_pr_discover_queue"); queued += cur.fetchone()[0]
    cur.execute(f"SELECT DISTINCT repo_name FROM {t}_repos"); repos |= {x[0] for x in cur.fetchall()}
json.dump({"rows": rows, "repositories": sorted(repos), "commits_queued": queued,
           "prs": pr}, open("data/derived/pr_layer.json", "w"))
print(f"rows {rows:,}  distinct {len(pr):,}  repos {len(repos):,}  queued {queued:,}")
