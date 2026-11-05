"""Active Directory operations over LDAPS (required for setting passwords)."""
import os, re, secrets, ssl, string, unicodedata
from contextlib import contextmanager

from ldap3 import Server, Connection, Tls, MODIFY_REPLACE, NONE
from ldap3.extend.microsoft.addMembersToGroups import ad_add_members_to_groups
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

AD_HOST = os.environ.get("AD_HOST", "")
AD_PORT = int(os.getenv("AD_PORT", "636"))
AD_BIND_USER = os.environ.get("AD_BIND_USER", "")
AD_BIND_PASSWORD = os.environ.get("AD_BIND_PASSWORD", "")
AD_BASE_DN = os.environ.get("AD_BASE_DN", "")
AD_UPN_SUFFIX = os.environ.get("AD_UPN_SUFFIX", "")
AD_CA_FILE = os.getenv("AD_CA_FILE", "/certs/ad-ca.pem")
AD_MAIL_DOMAIN = os.getenv("AD_MAIL_DOMAIN", AD_UPN_SUFFIX)


@contextmanager
def connect():
    tls = Tls(validate=ssl.CERT_REQUIRED,
              ca_certs_file=AD_CA_FILE if os.path.exists(AD_CA_FILE) else None)
    server = Server(AD_HOST, port=AD_PORT, use_ssl=True, tls=tls, get_info=NONE)
    conn = Connection(server, user=AD_BIND_USER, password=AD_BIND_PASSWORD,
                      auto_bind=True, raise_exceptions=True)
    try:
        yield conn
    finally:
        conn.unbind()


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _exists(conn, sam: str) -> bool:
    conn.search(AD_BASE_DN, f"(sAMAccountName={escape_filter_chars(sam)})", attributes=["cn"])
    return bool(conn.entries)


def make_username(conn, first: str, last: str) -> str:
    base = f"{_ascii(first)}.{_ascii(last)}"[:18].rstrip(".")
    if not base:
        raise ValueError("Cannot derive a username from the given name")
    sam, n = base, 1
    while _exists(conn, sam):
        n += 1
        sam = f"{base}{n}"
    return sam


def find_dn_by_mail(conn, mail: str):
    conn.search(AD_BASE_DN, f"(&(objectClass=user)(mail={escape_filter_chars(mail)}))",
                attributes=["distinguishedName"])
    return conn.entries[0].entry_dn if conn.entries else None


def gen_password(n=16) -> str:
    sets = [string.ascii_uppercase, string.ascii_lowercase, string.digits, "!@#$%^&*-_=+"]
    pw = [secrets.choice(s) for s in sets] + [secrets.choice("".join(sets)) for _ in range(n - 4)]
    secrets.SystemRandom().shuffle(pw)
    return "".join(pw)


def create_user(req: dict, ou: str, group_dns: list[str]) -> tuple[str, str]:
    """Create a DISABLED account with a random password. Returns (sAMAccountName, DN)."""
    with connect() as conn:
        sam = make_username(conn, req["first_name"], req["last_name"])
        display = f'{req["first_name"]} {req["last_name"]}'
        dn = f"CN={escape_rdn(display)},{ou}"
        if _exists(conn, sam):
            raise ValueError(f"{sam} already exists")
        attrs = {
            "sAMAccountName": sam,
            "userPrincipalName": f"{sam}@{AD_UPN_SUFFIX}",
            "givenName": req["first_name"],
            "sn": req["last_name"],
            "displayName": display,
            "mail": f"{sam}@{AD_MAIL_DOMAIN}",
            "title": req["job_title"],
            "department": req["department"],
            "description": f'Start date {req["start_date"]} (provisioned by HR agent)',
            "userAccountControl": 514,  # disabled until start date
        }
        mgr = find_dn_by_mail(conn, req["manager_email"])
        if mgr:
            attrs["manager"] = mgr
        conn.add(dn, ["top", "person", "organizationalPerson", "user"], attrs)
        conn.extend.microsoft.modify_password(dn, gen_password())
        if group_dns:
            ad_add_members_to_groups(conn, [dn], group_dns, fix=True)
        return sam, dn


def enable_user(dn: str) -> str:
    """Enable the account, set a new temp password (must change at first logon). Returns the password."""
    pw = gen_password()
    with connect() as conn:
        conn.extend.microsoft.modify_password(dn, pw)
        conn.modify(dn, {"pwdLastSet": [(MODIFY_REPLACE, [0])],
                         "userAccountControl": [(MODIFY_REPLACE, [512])]})
    return pw
