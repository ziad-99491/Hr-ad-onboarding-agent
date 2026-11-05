import json, logging, os, secrets
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import ad, agent, db, notify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hr-agent")
app = FastAPI(title="HR → AD Onboarding Agent")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
security = HTTPBasic()


def _auth(prefix: str):
    def dep(c: HTTPBasicCredentials = Depends(security)):
        ok = (secrets.compare_digest(c.username, os.environ[f"{prefix}_USER"]) &
              secrets.compare_digest(c.password, os.environ[f"{prefix}_PASSWORD"]))
        if not ok:
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
        return c.username
    return dep

hr_auth, admin_auth = _auth("HR"), _auth("ADMIN")


class HireRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=40)
    last_name: str = Field(min_length=1, max_length=40)
    job_title: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=60)
    manager_email: EmailStr
    start_date: date
    notes: str = Field(default="", max_length=500)

    @field_validator("start_date")
    @classmethod
    def not_past(cls, v):
        if v < date.today():
            raise ValueError("start_date cannot be in the past")
        return v


def provision(rid: str):
    row = db.get(rid)
    req, plan = json.loads(row["payload"]), json.loads(row["plan"])
    try:
        sam, dn = ad.create_user(req, plan["ou"], plan["group_dns"])
        db.update(rid, status="created", sam=sam, dn=dn, error=None)
        log.info("Created %s (%s), enable on %s", sam, rid, req["start_date"])
        enable_due()  # handles start_date == today
    except Exception as e:
        log.exception("Provisioning failed")
        db.update(rid, status="failed", error=str(e))


def process(rid: str):
    try:
        plan = agent.plan(json.loads(db.get(rid)["payload"]))
        db.update(rid, plan=json.dumps(plan))
        if plan["needs_review"]:
            db.update(rid, status="needs_review")
            log.warning("Request %s needs review: %s", rid, plan["flags"])
        else:
            provision(rid)
    except Exception as e:
        log.exception("Planning failed")
        db.update(rid, status="failed", error=str(e))


def enable_due():
    for row in db.list_due(date.today().isoformat()):
        req = json.loads(row["payload"])
        try:
            pw = ad.enable_user(row["dn"])
            notify.send_credentials(req["manager_email"], f'{req["first_name"]} {req["last_name"]}',
                                    row["sam"], f'{row["sam"]}@{ad.AD_UPN_SUFFIX}', pw, req["start_date"])
            db.update(row["id"], status="active", error=None)
            log.info("Enabled %s", row["sam"])
        except Exception as e:
            log.exception("Enable failed for %s", row["id"])
            db.update(row["id"], error=f"enable failed: {e}")


@app.on_event("startup")
def startup():
    db.init()
    sched = BackgroundScheduler()
    sched.add_job(enable_due, "interval", minutes=30)
    sched.start()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def form(request: Request, _=Depends(hr_auth)):
    return templates.TemplateResponse(request, "form.html")


@app.post("/api/requests", status_code=202)
def submit(r: HireRequest, bg: BackgroundTasks, _=Depends(hr_auth)):
    rid = db.create(json.loads(r.model_dump_json()))
    bg.add_task(process, rid)
    return {"id": rid, "status": "received"}


@app.get("/api/requests")
def list_requests(_=Depends(hr_auth)):
    return db.list_all()


@app.get("/api/requests/{rid}")
def status(rid: str, _=Depends(hr_auth)):
    row = db.get(rid)
    if not row:
        raise HTTPException(404)
    return {k: row[k] for k in ("id", "status", "start_date", "sam", "error")} | \
           {"plan": json.loads(row["plan"]) if row["plan"] else None}


@app.post("/api/requests/{rid}/approve")
def approve(rid: str, bg: BackgroundTasks, _=Depends(admin_auth)):
    row = db.get(rid)
    if not row or row["status"] != "needs_review":
        raise HTTPException(409, "Request is not awaiting review")
    plan = json.loads(row["plan"])
    if not plan.get("department_key"):
        plan["ou"] = agent.CATALOG["default_ou"]  # admin accepted the default OU
        db.update(rid, plan=json.dumps(plan))
    bg.add_task(provision, rid)
    return {"id": rid, "status": "approved"}


@app.post("/api/requests/{rid}/reject")
def reject(rid: str, _=Depends(admin_auth)):
    db.update(rid, status="rejected")
    return {"id": rid, "status": "rejected"}
