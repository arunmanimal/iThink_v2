"""
iThink Team page
----------------
Admins add people, change roles, reset passwords and remove people for their own workspace.

How people join: invitation only. An admin adds an e-mail address; the page creates the account with a one-time
temporary password that the admin passes on. The person must choose their own password at first login.
(No e-mail service is needed. Self sign-up is deliberately off for a multi-company product.)

Safety rules enforced here, not just in the screen:
  - the workspace (tenant) always comes from the signed-in admin's own membership, never from a form field;
  - every action re-checks in the database that the caller is an admin of that workspace;
  - nobody can remove themselves, change their own role, or remove the last admin.

Save as: app/team_page.py
"""
import secrets
import string

import pandas as pd
import streamlit as st

import theme

ROLES = ["admin", "analyst", "viewer"]
ROLE_HELP = {
    "admin": "Everything, plus managing the team.",
    "analyst": "Dashboards, AI, uploads and brand setup.",
    "viewer": "Dashboards and AI. Uploads and brand edits can be switched off per role in the app settings.",
}
PAGE_SIZE = 200


def temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12)) + "!"


def _caller_is_admin(admin, tenant_id: str, user_id: str) -> bool:
    rows = (admin.table("tenant_users").select("role").eq("tenant_id", tenant_id).eq("user_id", user_id)
            .execute().data or [])
    return bool(rows) and rows[0].get("role") == "admin"


def _members(admin, tenant_id: str) -> list:
    return (admin.table("tenant_users").select("user_id, email, role, must_change_password, created_at")
            .eq("tenant_id", tenant_id).order("created_at").execute().data or [])


def _find_auth_user(admin, email: str):
    """Looks through the accounts for one with this e-mail. Fine for a pilot-sized user base."""
    page = 1
    while page <= 20:
        batch = admin.auth.admin.list_users(page=page, per_page=PAGE_SIZE)
        users = batch if isinstance(batch, list) else getattr(batch, "users", []) or []
        for u in users:
            if (getattr(u, "email", "") or "").lower() == email.lower():
                return u
        if len(users) < PAGE_SIZE:
            return None
        page += 1
    return None


def add_member(admin, tenant_id: str, caller_id: str, email: str, role: str):
    """Returns (message, temporary_password_or_None). Raises ValueError with a message that is safe to show."""
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 200:
        raise ValueError("Enter a valid e-mail address.")
    if role not in ROLES:
        raise ValueError("Pick a role.")
    if not _caller_is_admin(admin, tenant_id, caller_id):
        raise ValueError("Only an admin can add people.")
    if any((m.get("email") or "").lower() == email for m in _members(admin, tenant_id)):
        raise ValueError("That person is already in this workspace.")
    password = temp_password()
    existing = _find_auth_user(admin, email)
    if existing is not None:
        elsewhere = admin.table("tenant_users").select("tenant_id").eq("user_id", existing.id).execute().data or []
        if elsewhere:
            raise ValueError("That e-mail already belongs to another workspace. Ask them to use a different address.")
        user_id = existing.id
        admin.auth.admin.update_user_by_id(user_id, {"password": password})
    else:
        created = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
        user_id = created.user.id
    admin.table("tenant_users").insert({"tenant_id": tenant_id, "user_id": user_id, "role": role, "email": email,
                                        "must_change_password": True}).execute()
    return f"Added {email} as {role}.", password


def apply_changes(admin, tenant_id: str, caller_id: str, edits: list):
    """edits: dicts with user_id, role, remove (bool), reset (bool). Returns a list of messages."""
    if not _caller_is_admin(admin, tenant_id, caller_id):
        raise ValueError("Only an admin can change the team.")
    members = {m["user_id"]: m for m in _members(admin, tenant_id)}
    admins = [m for m in members.values() if m["role"] == "admin"]
    messages, secrets_out = [], []
    for e in edits:
        m = members.get(e["user_id"])
        if not m:
            continue
        label = m.get("email") or m["user_id"]
        if e["user_id"] == caller_id:
            if e.get("remove") or e.get("role") != m["role"]:
                messages.append(f"You cannot remove yourself or change your own role ({label}).")
            if e.get("reset"):
                messages.append("Change your own password from the sidebar instead.")
            continue
        if e.get("remove"):
            if m["role"] == "admin" and len(admins) <= 1:
                messages.append(f"{label} is the last admin and cannot be removed.")
                continue
            admin.table("tenant_users").delete().eq("tenant_id", tenant_id).eq("user_id", e["user_id"]).execute()
            try:
                admin.auth.admin.delete_user(e["user_id"])
            except Exception:
                pass
            if m["role"] == "admin":
                admins = [a for a in admins if a["user_id"] != e["user_id"]]
            messages.append(f"Removed {label}.")
            continue
        if e.get("role") in ROLES and e["role"] != m["role"]:
            if m["role"] == "admin" and len(admins) <= 1:
                messages.append(f"{label} is the last admin, so the role was kept.")
            else:
                admin.table("tenant_users").update({"role": e["role"]}).eq("tenant_id", tenant_id) \
                    .eq("user_id", e["user_id"]).execute()
                if m["role"] == "admin":
                    admins = [a for a in admins if a["user_id"] != e["user_id"]]
                messages.append(f"{label} is now {e['role']}.")
        if e.get("reset"):
            password = temp_password()
            admin.auth.admin.update_user_by_id(e["user_id"], {"password": password})
            admin.table("tenant_users").update({"must_change_password": True}).eq("tenant_id", tenant_id) \
                .eq("user_id", e["user_id"]).execute()
            secrets_out.append((label, password))
            messages.append(f"Password reset for {label}.")
    return messages, secrets_out


# ---------------------------------------------------------------- screen
def _show_secrets():
    shown = st.session_state.get("tm_secrets") or []
    if not shown:
        return
    with st.container(border=True):
        st.warning("Pass this temporary password on now. It is shown once and the person must change it at first login.")
        for label, password in shown:
            st.write(label)
            st.code(password, language=None)
        st.button("I have copied it", key="tm_dismiss", on_click=lambda: st.session_state.pop("tm_secrets", None))


def render(admin, membership: dict, user):
    theme.page_header("Team", "Who can use this workspace")
    if admin is None:
        st.warning("Team management needs SUPABASE_SERVICE_ROLE_KEY in the app's secrets.")
        return
    tenant_id = (membership or {}).get("tenant_id")
    if not tenant_id or (membership or {}).get("role") != "admin":
        st.info("Only admins can manage the team.")
        return
    caller = user.id

    for text in st.session_state.pop("tm_flash", []) or []:
        if text.startswith(("You cannot", "Change your", "Only")) or "last admin" in text:
            st.warning(text)
        else:
            st.success(text)
    _show_secrets()

    st.subheader("Members")
    try:
        members = _members(admin, tenant_id)
    except Exception as e:
        st.error(f"Could not load the team. Has the Team SQL been run? Details: {e}")
        return
    frame = pd.DataFrame([{
        "Email": m.get("email") or "(unknown)",
        "Role": m["role"],
        "Status": "Must set a password" if m.get("must_change_password") else "Active",
        "Reset password": False,
        "Remove": False,
        "_id": m["user_id"],
    } for m in members])
    edited = st.data_editor(
        frame, hide_index=True, use_container_width=True, key="tm_editor",
        column_order=["Email", "Role", "Status", "Reset password", "Remove"],
        disabled=["Email", "Status"],
        column_config={"Role": st.column_config.SelectboxColumn("Role", options=ROLES, required=True),
                       "Reset password": st.column_config.CheckboxColumn("Reset password"),
                       "Remove": st.column_config.CheckboxColumn("Remove")})
    st.caption("  \n".join(f"**{r}**: {t}" for r, t in ROLE_HELP.items()))
    if st.button("Apply changes", key="tm_apply", type="primary"):
        edits = [{"user_id": row["_id"], "role": row["Role"], "remove": bool(row["Remove"]),
                  "reset": bool(row["Reset password"])} for _, row in edited.iterrows()]
        try:
            messages, passwords = apply_changes(admin, tenant_id, caller, edits)
        except Exception as e:
            st.error(str(e))
            return
        st.session_state["tm_flash"] = messages or ["No changes to apply."]
        if passwords:
            st.session_state["tm_secrets"] = passwords
        st.rerun()

    st.subheader("Add a person")
    with st.form("tm_add", clear_on_submit=True):
        email = st.text_input("E-mail address")
        role = st.selectbox("Role", ROLES, index=1)
        go = st.form_submit_button("Add person")
    if go:
        try:
            message, password = add_member(admin, tenant_id, caller, email, role)
        except ValueError as e:
            st.error(str(e))
        except Exception:
            st.error("Could not add that person. Check the e-mail address and try again.")
        else:
            st.session_state["tm_flash"] = [message]
            st.session_state["tm_secrets"] = [(email.strip().lower(), password)]
            st.rerun()
