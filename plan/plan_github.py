#!/usr/bin/env python3
"""
plan_github.py - make GitHub issues the ONLY place the BankUnited Implementation Plan is updated.

  reconcile  Excel -> GitHub, run ONCE to catch GitHub up to the latest Excel plan
             (e.g. the 10-29 file). Matches issues by Plan ID in the title ("T31 - ..."),
             creates missing ones, and updates title, plan fields, sprint milestone,
             owner/workstream labels and open/closed state. Also seeds a "Plan Change Log" issue.
             Preview by default; nothing changes until you add --apply.

  build      GitHub -> Excel, run every week (or let the GitHub Action do it). Rebuilds every
             row of the Implementation Plan, Blockers & Dependencies and Change Log sheets from
             the issues, using an existing plan file only as the formatting template.

Where each plan column lives in GitHub after reconcile:
  ID + Deliverable / Task  -> issue title  "T31 - Lessons learned ..."
  Sprint                   -> milestone    "S5 - Validate & Refine"
  Workstream               -> label        "ws: PM / Sponsor"
  Complete                 -> issue closed (closing an issue = 100%)
  Owner, Supporting, Start, Target Date, % Complete, Dependencies, Evidence, Notes
                           -> the "Plan fields" table in the issue body (edit it in the issue)
  Blockers                 -> issues labeled "blocker" (fields table: Tasks Affected, Decision ...)
  Change Log               -> the issue titled "Plan Change Log" (add a row to its table)

Auth: set GITHUB_TOKEN, or log in with the GitHub CLI (`gh auth login`); the script uses
`gh auth token` when GITHUB_TOKEN is not set. REST API only. Needs: Python 3.9+, openpyxl.

  python plan_github.py reconcile --plan "BankUnited Project Implementation_Plan_10-29_v3.xlsx"
  python plan_github.py reconcile --plan "BankUnited Project Implementation_Plan_10-29_v3.xlsx" --apply
  python plan_github.py build --template "BankUnited Project Implementation_Plan_10-29_v3.xlsx" --out plan_latest.xlsx
"""
import argparse, copy, datetime as dt, json, os, re, subprocess, sys, urllib.request, urllib.error
from pathlib import Path
import openpyxl

REPO = os.environ.get("PLAN_REPO", "Kottakotavenkatakeerthika/bankunited-market-expansion")
PLAN_SHEET, BLOCKER_SHEET, LOG_SHEET = "Implementation Plan", "Blockers & Dependencies", "Change Log"
SPRINTS = {"S0": ("Frame & Onboard", "2026-09-16"), "S1": ("Data Foundation", "2026-09-30"),
           "S2": ("Data Build & Test Planning", "2026-10-14"), "S3": ("Model Development & Demos", "2026-10-28"),
           "S4": ("MVP Integration", "2026-11-11"), "S5": ("Validate & Refine", "2026-11-25"),
           "S6": ("Deliver & Hand Off", "2026-12-10")}
# Owner label = "owner: <first name>", matching the labels already on the repo's issues.
ROSTER = ["Akayiah Bell", "Kottakota Venkata", "Sonia Chavelas Gonzalez", "Austin Edwards", "Bhavana Vasireddy",
          "Matt D'Allaird", "Jainesh Lad", "Evan de Guzman", "Varun Sawant"]
TASK_FIELDS = ["Plan ID", "Owner", "Supporting", "Start", "Target", "% Complete", "Dependencies", "Evidence", "Notes"]
BLOCKER_FIELDS = ["Plan ID", "Tasks Affected", "Decision / Action Needed", "Owner", "Decision From", "Needed By", "Status"]
LOG_COLUMNS = ["Date", "Change", "Reason", "Impact on Plan"]
LOG_TITLE, LOG_LABEL = "Plan Change Log", "plan-changelog"
START, END = "<!-- plan-fields:start -->", "<!-- plan-fields:end -->"
HELP_LINE = "_Edit the values in this table to update the Implementation Plan. Close the issue when it is 100% done._"
PID_RE = re.compile(r"^\s*([TB]\d{1,3})\b")


# ------------------------------------------------------------------------------- GitHub (REST)
class GitHub:
    def __init__(self, repo, token=None, apply=False):
        self.repo, self.apply = repo, apply
        self.token = token or os.environ.get("GITHUB_TOKEN") or self._gh_token()

    @staticmethod
    def _gh_token():
        try:
            return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            sys.exit("No GitHub token: set GITHUB_TOKEN or run `gh auth login`.")

    def _call(self, method, path, body=None):
        url = path if path.startswith("http") else f"https://api.github.com/repos/{self.repo}{path}"
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return json.loads(data) if data else None, r.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code == 422 and method == "POST" and path == "/labels":
                return None, ""                                        # label already exists
            sys.exit(f"GitHub {method} {path} failed ({e.code}): {e.read().decode()[:400]}")

    def _all(self, path):
        out, url = [], f"https://api.github.com/repos/{self.repo}{path}"
        while url:
            data, link = self._call("GET", url)
            out += data
            m = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = m.group(1) if m else None
        return out

    def issues(self):
        return [i for i in self._all("/issues?state=all&per_page=100") if "pull_request" not in i]

    def milestones(self):
        return self._all("/milestones?state=all&per_page=100")

    def create_milestone(self, title, due):
        return self._call("POST", "/milestones", {"title": title, "due_on": f"{due}T23:59:59Z"})[0]

    def ensure_label(self, name):
        self._call("POST", "/labels", {"name": name, "color": "6B6B1F" if name.startswith("ws:") else "C5C58A"})

    def create_issue(self, payload):
        return self._call("POST", "/issues", payload)[0]

    def update_issue(self, number, payload):
        return self._call("PATCH", f"/issues/{number}", payload)[0]


class FakeGitHub(GitHub):
    """Offline stand-in that reads and writes a JSON file instead of GitHub (for testing)."""
    def __init__(self, path, apply=False):
        self.path, self.apply, self.repo = Path(path), apply, "fixture"
        self.db = json.loads(self.path.read_text()) if self.path.exists() else {"issues": [], "milestones": [], "labels": []}

    def save(self):
        self.path.write_text(json.dumps(self.db, indent=1, default=str))

    def issues(self): return copy.deepcopy(self.db["issues"])
    def milestones(self): return copy.deepcopy(self.db["milestones"])

    def create_milestone(self, title, due):
        m = {"number": len(self.db["milestones"]) + 1, "title": title, "due_on": due}
        self.db["milestones"].append(m); self.save(); return m

    def ensure_label(self, name):
        if name not in self.db["labels"]:
            self.db["labels"].append(name); self.save()

    def _ms(self, n):
        return next((m for m in self.db["milestones"] if m["number"] == n), None)

    def create_issue(self, p):
        i = {"number": max([x["number"] for x in self.db["issues"]] + [100]) + 1, "title": p["title"],
             "body": p.get("body", ""), "state": "open", "labels": [{"name": l} for l in p.get("labels", [])],
             "milestone": self._ms(p.get("milestone"))}
        self.db["issues"].append(i); self.save(); return i

    def update_issue(self, number, p):
        i = next(x for x in self.db["issues"] if x["number"] == number)
        for k, v in p.items():
            if k == "labels": i["labels"] = [{"name": l} for l in v]
            elif k == "milestone": i["milestone"] = self._ms(v)
            elif k != "state_reason": i[k] = v
        self.save(); return i


# ------------------------------------------------------------------------------- body table
def esc(v):
    return str(v).replace("\\", "\\\\").replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def unesc(v):
    return v.replace("<br>", "\n").replace("\\|", "|").replace("\\\\", "\\").strip()


def render_block(fields, values, heading="Plan fields"):
    rows = "\n".join(f"| {f} | {esc(values.get(f, '') or '')} |" for f in fields)
    return f"{START}\n### {heading}\n| Field | Value |\n| --- | --- |\n{rows}\n\n{HELP_LINE}\n{END}"


def split_row(line):
    cells, cur, i = [], "", 0
    s = line.strip().strip("|") if not line.strip().endswith("\\|") else line.strip()[1:]
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            cur += s[i:i + 2]; i += 2; continue
        if s[i] == "|":
            cells.append(cur); cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur)
    return [unesc(c) for c in cells]


def parse_block(body):
    """Return {field: value} from the managed table, or {} if the issue has none yet."""
    body = body or ""
    if START not in body:
        return {}
    block = body.split(START, 1)[1].split(END, 1)[0]
    out = {}
    for line in block.splitlines():
        if line.strip().startswith("|") and "---" not in line:
            cells = split_row(line)
            if len(cells) >= 2 and cells[0] not in ("Field", ""):
                out[cells[0]] = cells[1]
    return out


def parse_table(body, columns):
    """Rows of a multi-column managed table (used by the Change Log issue)."""
    body = body or ""
    if START not in body:
        return []
    rows = []
    for line in body.split(START, 1)[1].split(END, 1)[0].splitlines():
        if line.strip().startswith("|") and "---" not in line:
            cells = split_row(line)
            if cells[0] != columns[0]:
                rows.append(dict(zip(columns, cells + [""] * len(columns))))
    return rows


def with_block(old_body, block):
    old_body = old_body or ""
    if START in old_body and END in old_body:
        pre, rest = old_body.split(START, 1)
        return pre + block + rest.split(END, 1)[1]
    if old_body.strip():   # first reconcile: keep the original import text, folded away
        return f"{block}\n\n<details><summary>Original import text</summary>\n\n{old_body}\n\n</details>"
    return block


# ------------------------------------------------------------------------------- Excel helpers
def iso(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip() if v not in (None, "") else ""


def to_date(s):
    try:
        return dt.datetime.strptime(str(s).strip()[:10], "%Y-%m-%d")
    except ValueError:
        try:
            return dt.datetime.strptime(str(s).strip(), "%m/%d/%Y")
        except ValueError:
            return s or None


def pct_text(v):
    try:
        return f"{round(float(v) * 100)}%"
    except (TypeError, ValueError):
        return "0%"


def pct_value(s):
    m = re.search(r"-?\d+(\.\d+)?", str(s or ""))
    if not m:
        return 0.0
    x = float(m.group())
    return max(0.0, min(1.0, x / 100 if x > 1 or "%" in str(s) else x))


def header(ws, id_col):
    for r in range(1, 40):
        if str(ws.cell(r, id_col).value).strip() == "ID":
            return r, {str(c.value).strip(): c.column for c in ws[r] if c.value}
    sys.exit(f"No header row with 'ID' in sheet '{ws.title}'.")


def read_excel(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[PLAN_SHEET]
    hr, H = header(ws, 2)
    g = lambda r, n: ws.cell(r, H[n]).value if n in H else None
    tasks = []
    for r in range(hr + 1, ws.max_row + 1):
        pid = g(r, "ID")
        if isinstance(pid, str) and PID_RE.match(pid) and pid.startswith("T"):
            tasks.append({"Plan ID": pid, "Sprint": g(r, "Sprint"), "Workstream": g(r, "Workstream"),
                          "Title": g(r, "Deliverable / Task"), "Owner": g(r, "Owner") or "",
                          "Supporting": g(r, "Supporting") or "", "Start": iso(g(r, "Start")),
                          "Target": iso(g(r, "Target Date")), "% Complete": pct_text(g(r, "% Complete")),
                          "pct": float(g(r, "% Complete") or 0), "Dependencies": g(r, "Dependencies") or "",
                          "Evidence": g(r, "Sponsor Checkpoint / Evidence") or "", "Notes": g(r, "Notes") or ""})
    blockers = []
    bs = wb[BLOCKER_SHEET]
    hb, HB = header(bs, 1)
    gb = lambda r, n: bs.cell(r, HB[n]).value if n in HB else None
    for r in range(hb + 1, bs.max_row + 1):
        pid = gb(r, "ID")
        if isinstance(pid, str) and pid.startswith("B") and PID_RE.match(pid):
            blockers.append({"Plan ID": pid, "Title": gb(r, "Issue / Dependency"),
                             "Tasks Affected": gb(r, "Tasks Affected") or "",
                             "Decision / Action Needed": gb(r, "Decision / Action Needed") or "",
                             "Owner": gb(r, "Owner") or "", "Decision From": gb(r, "Decision From") or "",
                             "Needed By": iso(gb(r, "Needed By")), "Status": str(gb(r, "Status") or "")})
    log = []
    if LOG_SHEET in wb.sheetnames:
        ls = wb[LOG_SHEET]
        for r in range(1, ls.max_row + 1):
            if isinstance(ls.cell(r, 1).value, (dt.date, dt.datetime)):
                log.append({"Date": iso(ls.cell(r, 1).value), "Change": ls.cell(r, 2).value or "",
                            "Reason": ls.cell(r, 3).value or "", "Impact on Plan": ls.cell(r, 4).value or ""})
    return tasks, blockers, log


def owner_labels(*names):
    out = []
    for n in names:
        for part in re.split(r"[;,]", str(n or "")):
            part = part.strip()
            if part in ROSTER:
                out.append(f"owner: {part.split()[0]}")
    return list(dict.fromkeys(out))


def labels_of(issue):
    return [l["name"] if isinstance(l, dict) else l for l in issue.get("labels", [])]


def pid_of(issue):
    m = PID_RE.match(issue.get("title", ""))
    return m.group(1) if m else parse_block(issue.get("body")).get("Plan ID")


# ------------------------------------------------------------------------------- reconcile
def cmd_reconcile(a, hub):
    tasks, blockers, log = read_excel(a.plan)
    issues = hub.issues()
    by_pid = {}
    for i in issues:
        p = pid_of(i)
        if p:
            if p in by_pid:
                print(f"! two issues claim {p}: #{by_pid[p]['number']} and #{i['number']} (using the first)")
                continue
            by_pid[p] = i
    ms = {m["title"].split(" ")[0]: m for m in hub.milestones()}
    print(f"Excel: {len(tasks)} tasks, {len(blockers)} blockers, {len(log)} change-log rows | "
          f"GitHub: {len(issues)} issues, {len(by_pid)} with a Plan ID\n")
    counts = {"create": 0, "update": 0, "same": 0}

    def milestone_for(sprint):
        if not sprint:
            return None
        if sprint not in ms:
            name, due = SPRINTS.get(sprint, (sprint, "2026-12-10"))
            print(f"  + milestone {sprint} - {name}")
            ms[sprint] = hub.create_milestone(f"{sprint} - {name}", due) if hub.apply else {"number": None, "title": sprint}
        return ms[sprint]["number"]

    def sync(pid, title, block, kind_labels, managed_prefixes, closed, milestone, extra_add=()):
        nonlocal counts
        cur = by_pid.get(pid)
        want_labels_managed = kind_labels
        if cur is None:
            payload = {"title": title, "body": block, "labels": list(dict.fromkeys(want_labels_managed + list(extra_add)))}
            if milestone: payload["milestone"] = milestone
            print(f"create {pid:4} {title[:72]}")
            counts["create"] += 1
            if hub.apply:
                for l in payload["labels"]: hub.ensure_label(l)
                new = hub.create_issue(payload)
                if closed: hub.update_issue(new["number"], {"state": "closed", "state_reason": "completed"})
            return
        keep = [l for l in labels_of(cur) if not l.startswith(managed_prefixes)]
        labels = list(dict.fromkeys(keep + want_labels_managed + list(extra_add)))
        body = with_block(cur.get("body"), block)
        payload, what = {}, []
        if cur["title"] != title: payload["title"] = title; what.append("title")
        if parse_block(cur.get("body")) != parse_block(block) or START not in (cur.get("body") or ""):
            payload["body"] = body; what.append("fields")
        if sorted(labels) != sorted(labels_of(cur)): payload["labels"] = labels; what.append("labels")
        cur_ms = (cur.get("milestone") or {}).get("number")
        if milestone is not None and cur_ms != milestone: payload["milestone"] = milestone; what.append("sprint")
        state = "closed" if closed else "open"
        if cur["state"] != state:
            payload["state"] = state; what.append(f"-> {state}")
            if closed: payload["state_reason"] = "completed"
        if payload:
            counts["update"] += 1
            print(f"update {pid:4} #{cur['number']:<4} {', '.join(what)}")
            if hub.apply:
                for l in payload.get("labels", []): hub.ensure_label(l)
                hub.update_issue(cur["number"], payload)
        else:
            counts["same"] += 1

    for t in tasks:
        block = render_block(TASK_FIELDS, t)
        labels = ["plan-task"] + ([f"ws: {t['Workstream']}"] if t["Workstream"] else []) + owner_labels(t["Owner"])
        sync(t["Plan ID"], f"{t['Plan ID']} - {t['Title']}", block, labels, ("owner:", "ws:", "plan-task"),
             t["pct"] >= 1, milestone_for(t["Sprint"]))
    for b in blockers:
        block = render_block(BLOCKER_FIELDS, b, "Blocker fields")
        extra = ["sponsor-decision"] if re.search(r"liaison|sponsor", b["Decision From"], re.I) else []
        sync(b["Plan ID"], f"{b['Plan ID']} - {b['Title']}", block, ["blocker"] + owner_labels(b["Owner"]),
             ("owner:", "blocker"), b["Status"].lower().startswith("closed"), None, extra)

    # change log issue
    table = "| " + " | ".join(LOG_COLUMNS) + " |\n|" + " --- |" * len(LOG_COLUMNS) + "\n" + "\n".join(
        "| " + " | ".join(esc(r[c]) for c in LOG_COLUMNS) + " |" for r in log)
    log_block = (f"{START}\n### Change log\n{table}\n\n_Add a row to this table for each plan change "
                 f"(date as YYYY-MM-DD)._\n{END}")
    cur = next((i for i in issues if i["title"] == LOG_TITLE), None)
    if cur is None:
        print(f"create      {LOG_TITLE} ({len(log)} rows)"); counts["create"] += 1
        if hub.apply:
            hub.ensure_label(LOG_LABEL)
            hub.create_issue({"title": LOG_TITLE, "body": log_block, "labels": [LOG_LABEL]})
    elif parse_table(cur.get("body"), LOG_COLUMNS) != parse_table(log_block, LOG_COLUMNS):
        print(f"update      {LOG_TITLE} #{cur['number']} ({len(log)} rows)"); counts["update"] += 1
        if hub.apply:
            hub.update_issue(cur["number"], {"body": with_block(cur.get("body"), log_block)})
    else:
        counts["same"] += 1

    print(f"\n{counts['create']} to create, {counts['update']} to update, {counts['same']} already match.")
    print("Applied." if hub.apply else "Preview only. Add --apply to make these changes.")


# ------------------------------------------------------------------------------- build
def grab_row_style(ws, r, ncols):
    return [(copy.copy(ws.cell(r, c).font), copy.copy(ws.cell(r, c).fill), copy.copy(ws.cell(r, c).border),
             copy.copy(ws.cell(r, c).alignment), ws.cell(r, c).number_format) for c in range(1, ncols + 1)]


def put_style(cell, st):
    cell.font, cell.fill, cell.border, cell.alignment, cell.number_format = st


def rewrite_ranges(ws, upto_row, first, old_last, new_last):
    pat = re.compile(rf"(\$?[A-Z]{{1,3}}\$?){first}:(\$?[A-Z]{{1,3}}\$?){old_last}(?!\d)")
    for row in ws.iter_rows(min_row=1, max_row=upto_row):
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                c.value = pat.sub(lambda m: f"{m.group(1)}{first}:{m.group(2)}{new_last}", c.value)


def replace_table(ws, hr, ncols, rows, write_row, trailer=True):
    """Delete every row under the header, then write `rows` and re-append the trailer (legend)."""
    last_data = hr
    for r in range(hr + 1, ws.max_row + 1):
        if ws.cell(r, 2 if ws.title == PLAN_SHEET else 1).value not in (None, ""):
            if PID_RE.match(str(ws.cell(r, 2 if ws.title == PLAN_SHEET else 1).value)) or ws.title == LOG_SHEET:
                last_data = r
    styles = [grab_row_style(ws, r, ncols) for r in range(hr + 1, min(hr + 3, last_data + 1))] or \
             [grab_row_style(ws, hr + 1, ncols)]
    tail = []
    if trailer:
        for r in range(last_data + 1, ws.max_row + 1):
            tail.append([(ws.cell(r, c).value, grab_row_style(ws, r, ncols)[c - 1]) for c in range(1, ncols + 1)])
    heights = {r - hr: ws.row_dimensions[r].height for r in range(hr + 1, ws.max_row + 1)}
    if ws.max_row > hr:
        ws.delete_rows(hr + 1, ws.max_row - hr)
    for k, item in enumerate(rows):
        r = hr + 1 + k
        st = styles[k % len(styles)]
        for c, v in enumerate(write_row(r, item), 1):
            cell = ws.cell(r, c, v)
            put_style(cell, st[c - 1])
    new_last = hr + len(rows)
    for k, row in enumerate(tail):
        r = new_last + 1 + k
        for c, (v, st) in enumerate(row, 1):
            cell = ws.cell(r, c, v)
            put_style(cell, st)
    for r in range(hr + 1, ws.max_row + 1):
        ws.row_dimensions[r].height = None
    return last_data, new_last


def cmd_build(a, hub):
    issues = hub.issues()
    tasks, blockers, log_issue = [], [], None
    for i in issues:
        if i["title"] == LOG_TITLE:
            log_issue = i; continue
        p = pid_of(i)
        if not p:
            continue
        f = parse_block(i.get("body"))
        labels = labels_of(i)
        if p.startswith("T"):
            ms = (i.get("milestone") or {}).get("title", "")
            ws_label = next((l[3:].strip() for l in labels if l.startswith("ws:")), "")
            pct = 1.0 if i["state"] == "closed" else pct_value(f.get("% Complete"))
            tasks.append({"pid": p, "num": i["number"], "Sprint": ms.split(" ")[0] if ms else "",
                          "Workstream": ws_label, "Title": PID_RE.sub("", i["title"]).lstrip(" -–:"),
                          "Owner": f.get("Owner", ""), "Supporting": f.get("Supporting", ""),
                          "Start": to_date(f.get("Start")), "Target": to_date(f.get("Target")), "pct": pct,
                          "Dependencies": f.get("Dependencies", ""), "Evidence": f.get("Evidence", ""),
                          "Notes": f.get("Notes", ""), "has_block": bool(f)})
        else:
            status = f.get("Status", "")
            if i["state"] == "closed" and not status.lower().startswith("closed"):
                status = f"Closed{(' – ' + status) if status else ''}"
            blockers.append({"pid": p, "num": i["number"], "Title": PID_RE.sub("", i["title"]).lstrip(" -–:"),
                             **{k: f.get(k, "") for k in BLOCKER_FIELDS[1:]}, "Status": status, "has_block": bool(f)})
    order = list(SPRINTS)
    tasks.sort(key=lambda t: (order.index(t["Sprint"]) if t["Sprint"] in order else 99, t["num"]))
    blockers.sort(key=lambda b: int(b["pid"][1:]))
    missing = [t["pid"] for t in tasks + blockers if not t["has_block"]]

    wb = openpyxl.load_workbook(a.template)
    ws = wb[PLAN_SHEET]
    hr, H = header(ws, 2)
    ncols = max(H.values())
    cols = ["Sprint", "ID", "Workstream", "Deliverable / Task", "Owner", "Supporting", "Start", "Target Date",
            "% Complete", "Status", "Dependencies", "Sponsor Checkpoint / Evidence", "Notes"]
    if [k for k in cols if k not in H]:
        sys.exit(f"Template is missing columns: {[k for k in cols if k not in H]}")

    def task_row(r, t):
        vals = {"Sprint": t["Sprint"], "ID": t["pid"], "Workstream": t["Workstream"], "Deliverable / Task": t["Title"],
                "Owner": t["Owner"], "Supporting": t["Supporting"] or None, "Start": t["Start"],
                "Target Date": t["Target"], "% Complete": t["pct"],
                "Status": f'=IF({col("% Complete")}{r}>=1,"Complete",IF(AND({col("Target Date")}{r}<$B$4,'
                          f'{col("% Complete")}{r}<1),"Overdue",IF({col("% Complete")}{r}>0,"In Progress","Not Started")))',
                "Dependencies": t["Dependencies"] or None, "Sponsor Checkpoint / Evidence": t["Evidence"] or None,
                "Notes": t["Notes"] or None}
        out = [None] * ncols
        for k, c in H.items():
            if k in vals: out[c - 1] = vals[k]
        return out

    col = lambda name: openpyxl.utils.get_column_letter(H[name])
    old_last, new_last = replace_table(ws, hr, ncols, tasks, task_row)
    rewrite_ranges(ws, hr - 1, hr + 1, old_last, new_last)
    as_of = dt.datetime.strptime(a.as_of, "%Y-%m-%d") if a.as_of else dt.datetime.combine(
        (dt.datetime.utcnow() - dt.timedelta(hours=4)).date(), dt.time())
    for r in range(1, hr):
        if str(ws.cell(r, 1).value).strip().lower() == "as-of date":
            ws.cell(r, 2).value = as_of
    for r in range(new_last + 1, ws.max_row + 1):
        v = ws.cell(r, 2).value
        if isinstance(v, str) and v.startswith("Links:"):
            ws.cell(r, 2).value = (f"Links: Repository github.com/{hub.repo} · Generated from GitHub issues on "
                                   f"{as_of:%m/%d/%Y}; edit issues, not this file.")

    bs = wb[BLOCKER_SHEET]
    hb, HB = header(bs, 1)
    bcols = {"ID": "pid", "Issue / Dependency": "Title", "Tasks Affected": "Tasks Affected",
             "Decision / Action Needed": "Decision / Action Needed", "Owner": "Owner",
             "Decision From": "Decision From", "Needed By": "Needed By", "Status": "Status"}

    def blocker_row(r, b):
        out = [None] * max(HB.values())
        for k, c in HB.items():
            if k in bcols:
                v = b[bcols[k]]
                out[c - 1] = to_date(v) if k == "Needed By" and v else (v or None)
        return out
    replace_table(bs, hb, max(HB.values()), blockers, blocker_row)

    log_rows = parse_table(log_issue.get("body"), LOG_COLUMNS) if log_issue else []
    if LOG_SHEET in wb.sheetnames and log_issue:
        ls = wb[LOG_SHEET]
        hl = next(r for r in range(1, 40) if str(ls.cell(r, 1).value).strip() == "Date")
        replace_table(ls, hl, 4, log_rows,
                      lambda r, x: [to_date(x["Date"]), x["Change"], x["Reason"], x["Impact on Plan"]], trailer=False)

    wb.calculation.fullCalcOnLoad = True          # Excel recalculates Status and totals on open
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Built {out}: {len(tasks)} tasks, {len(blockers)} blockers, {len(log_rows)} change-log rows "
          f"(as of {as_of:%m/%d/%Y}).")
    if missing:
        print(f"! {len(missing)} issue(s) have no Plan fields table yet (run reconcile): {', '.join(missing[:12])}"
              + (" ..." if len(missing) > 12 else ""))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=REPO)
    p.add_argument("--fixture", help=argparse.SUPPRESS)       # offline JSON stand-in for GitHub (testing)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reconcile", help="one-time: bring GitHub up to date with an Excel plan")
    r.add_argument("--plan", required=True); r.add_argument("--apply", action="store_true")
    b = sub.add_parser("build", help="weekly: regenerate the Excel plan from GitHub")
    b.add_argument("--template", required=True, help="latest plan file, used for formatting only")
    b.add_argument("--out", required=True); b.add_argument("--as-of", help="YYYY-MM-DD (default: today)")
    a = p.parse_args()
    apply = getattr(a, "apply", False)
    hub = FakeGitHub(a.fixture, apply) if a.fixture else GitHub(a.repo, apply=apply)
    cmd_reconcile(a, hub) if a.cmd == "reconcile" else cmd_build(a, hub)
