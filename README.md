# HR → Active Directory Onboarding Agent

Flow: HR form → AI plans OU/groups (validated against catalog.json) → disabled AD account created
→ on the start date the account is enabled, a temp password is set (must change at first logon)
and emailed to the hiring manager. Anything ambiguous/privileged goes to `needs_review`.

## Run
    cp .env.example .env        # fill in values
    cp /path/to/domain-ca.pem certs/ad-ca.pem
    # edit catalog.json to match your OUs and groups
    docker compose up -d --build
    open http://<host>:8000     # HR form (Basic auth)

## IT review
    curl -u itadmin:PASS -X POST http://host:8000/api/requests/<id>/approve   # or /reject

## AD prerequisites
- Service account with delegated rights ONLY on the target OUs: Create/Delete User objects,
  Reset Password, write userAccountControl/pwdLastSet/attributes, and add members to the listed groups.
- LDAPS (636) enabled on the DC; the container must reach it. Mount the CA cert at certs/ad-ca.pem.
- Put the app behind an HTTPS reverse proxy (Basic auth is otherwise sent in clear text).
