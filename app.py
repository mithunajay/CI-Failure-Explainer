"""MySQL-backed Streamlit interface for the CI Failure Explainer."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import streamlit as st
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ci_explainer.auth import (
    authenticate,
    change_password,
    create_account,
    ensure_bootstrap_admin,
    request_email_verification,
    request_password_reset,
    reset_password_with_otp,
    reset_password,
    set_account_active,
    verify_email_otp,
)
from ci_explainer.database import (
    User,
    create_database_engine,
    initialize_database,
    list_accounts,
    list_analyses,
    save_analysis,
)
from ci_explainer.web_backend import explain_log


ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "data" / "sample"
SAMPLES = {path.stem: path for path in sorted(SAMPLE_DIR.glob("*.log"))}


@st.cache_resource
def get_engine(url: URL):
    engine = create_database_engine(url)
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return engine


def show_explanation(result: dict) -> None:
    st.subheader("Explanation")
    st.write(result["summary"])
    columns = st.columns(3)
    columns[0].metric("Category", result["category"].replace("_", " ").title())
    columns[1].metric("Confidence", result["confidence"].title())
    columns[2].metric("Source", result["source"].replace("_", " ").title())
    st.markdown("**Likely cause**")
    st.write(result["root_cause"])
    if result["evidence"]:
        st.markdown("**Evidence from the log**")
        for quote in result["evidence"]:
            st.code(quote, language=None)
    st.markdown("**Suggested next steps**")
    for fix in result["suggested_fix"]:
        st.markdown(f"- {fix}")
    if result["injection_flags"]:
        st.warning(
            "Instruction-like or delimiter-like text was found: "
            + ", ".join(result["injection_flags"])
            + ". The log was treated as untrusted input."
        )
    if result["redactions"]:
        st.info(f"Redacted {result['redactions']} possible secret value(s) before analysis.")
    if result["errors"]:
        st.warning("The model response was rejected; the rule-based fallback was shown.")
        for error in result["errors"]:
            st.caption(error)
    with st.expander("Run details"):
        st.write(f"Input tokens: {result['input_tokens']}")
        st.write(f"Output tokens: {result['output_tokens']}")
        st.write(f"Model latency: {result['latency_s']:.2f} seconds")


def show_login(session: Session) -> bool:
    current_user = st.session_state.get("auth_user")
    if current_user:
        record = session.get(User, current_user["id"])
        if record and record.active:
            current_user.update(username=record.username, role=record.role)
            return True
        st.session_state.pop("auth_user", None)
        st.warning("This account is no longer active. Please sign in again.")

    login_tab, signup_tab, recovery_tab = st.tabs(
        ["Sign in", "Create account", "Forgot password"]
    )
    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary")
        if submitted:
            try:
                user = authenticate(session, username, password)
            except SQLAlchemyError:
                session.rollback()
                st.error("Could not verify the account. Check the MySQL connection.")
                return False
            if user is None:
                st.error(
                    "Sign-in failed. Check your username/password and confirm your email is verified."
                )
            else:
                st.session_state["auth_user"] = user
                st.rerun()

    otp_secret = os.environ.get("APP_OTP_SECRET", "")
    with signup_tab:
        st.caption("Create an account and verify your email before signing in.")
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username")
            new_email = st.text_input("Email address")
            new_password = st.text_input("Choose a password (at least 12 characters)", type="password")
            submitted = st.form_submit_button("Create account")
        if submitted:
            try:
                create_account(session, new_username, new_password, new_email)
            except ValueError as error:
                session.rollback()
                st.error(str(error))
            except SQLAlchemyError:
                session.rollback()
                st.error("Could not create the account. Check the database connection.")
            else:
                st.session_state["pending_verification_email"] = new_email.strip().casefold()
                try:
                    request_email_verification(session, new_email, otp_secret)
                    st.success(
                        f"Account created. Enter the verification code sent to {new_email.strip()}."
                    )
                except RuntimeError as error:
                    st.error(
                        f"Account created, but the verification email was not sent: {error} "
                        "Configure email and use Resend verification code."
                    )

        pending_email = st.session_state.get("pending_verification_email")
        if pending_email:
            st.markdown("**Verify your email**")
            with st.form("verify_email_form"):
                verification_code = st.text_input("Six-digit email code", max_chars=6)
                verify = st.form_submit_button("Verify email")
            if verify:
                try:
                    verified = verify_email_otp(
                        session, pending_email, verification_code.strip(), otp_secret
                    )
                except RuntimeError as error:
                    st.error(str(error))
                else:
                    if verified:
                        st.session_state.pop("pending_verification_email", None)
                        st.success("Email verified. You can now sign in.")
                    else:
                        st.error("Code is invalid, expired, or has reached its attempt limit.")
            if st.button("Resend verification code"):
                try:
                    sent = request_email_verification(session, pending_email, otp_secret)
                    if sent:
                        st.success("A new verification code was sent.")
                    else:
                        st.info("Please wait before requesting another code.")
                except RuntimeError as error:
                    st.error(str(error))

        with st.form("resend_verification_form"):
            resend_email = st.text_input("Resend verification code to email")
            resend = st.form_submit_button("Send verification code")
        if resend:
            try:
                request_email_verification(session, resend_email, otp_secret)
            except RuntimeError as error:
                st.error(str(error))
            else:
                st.info(
                    "If that address belongs to an active unverified account, "
                    "a code has been emailed."
                )

    with recovery_tab:
        st.caption("We send a short-lived code only if the address belongs to a verified account.")
        with st.form("request_reset_form"):
            reset_email = st.text_input("Account email address")
            request_reset = st.form_submit_button("Send recovery code")
        if request_reset:
            st.session_state["pending_reset_email"] = reset_email.strip().casefold()
            try:
                request_password_reset(session, reset_email, otp_secret)
            except RuntimeError as error:
                st.error(str(error))
            else:
                st.info(
                    "If that address belongs to an active verified account, a code has been emailed."
                )

        pending_reset_email = st.session_state.get("pending_reset_email")
        if pending_reset_email:
            with st.form("complete_reset_form"):
                recovery_code = st.text_input("Six-digit recovery code", max_chars=6)
                replacement_password = st.text_input(
                    "New password (at least 12 characters)", type="password"
                )
                finish_reset = st.form_submit_button("Reset password")
            if finish_reset:
                try:
                    changed = reset_password_with_otp(
                        session,
                        pending_reset_email,
                        recovery_code.strip(),
                        replacement_password,
                        otp_secret,
                    )
                except (RuntimeError, ValueError) as error:
                    st.error(str(error))
                else:
                    if changed:
                        st.session_state.pop("pending_reset_email", None)
                        st.success("Password reset. You can now sign in.")
                    else:
                        st.error("Code is invalid, expired, or has reached its attempt limit.")
    return False


def show_analysis_tab(user: dict, session: Session, settings: dict) -> None:
    st.info(
        "Anthropic mode sends the cleaned, redacted log to Anthropic. "
        "Review sensitive logs before submitting."
    )
    sample_choice = st.selectbox("Example log", ("Paste or upload your own", *SAMPLES.keys()))
    sample_text = (
        SAMPLES[sample_choice].read_text(encoding="utf-8", errors="replace")
        if sample_choice in SAMPLES
        else ""
    )
    with st.form("analysis_form"):
        uploaded_file = st.file_uploader("Or upload a CI log", type=("log", "txt"))
        raw_log = st.text_area(
            "CI log",
            value=sample_text,
            height=320,
            key=f"log_input_{sample_choice}",
            placeholder="Paste the failed job's log here...",
        )
        submitted = st.form_submit_button("Analyze log", type="primary")

    if submitted:
        try:
            max_bytes = settings["max_upload_mb"] * 1024 * 1024
            if uploaded_file is not None:
                if uploaded_file.size > max_bytes:
                    raise ValueError(
                        f"File exceeds the {settings['max_upload_mb']} MB limit."
                    )
                log_text = uploaded_file.getvalue().decode("utf-8", errors="replace")
            else:
                log_text = raw_log
                if len(log_text.encode("utf-8")) > max_bytes:
                    raise ValueError(
                        f"Pasted log exceeds the {settings['max_upload_mb']} MB limit."
                    )

            with st.spinner("Analyzing the CI log..."):
                explanation = explain_log(
                    log_text,
                    use_model=settings["mode"] == "Anthropic model",
                    model=settings["model"].strip() or None,
                    api_key=settings["api_key"] or None,
                    max_tokens=settings["max_tokens"],
                )
            result = explanation.to_dict()
            st.session_state["last_explanation"] = result
            try:
                save_analysis(session, user, log_text, result)
                st.success("Analysis saved to your private history.")
            except SQLAlchemyError:
                session.rollback()
                st.error("Analysis succeeded but could not be saved to MySQL.")
        except (ValueError, RuntimeError) as error:
            st.session_state.pop("last_explanation", None)
            st.error(str(error))

    if "last_explanation" in st.session_state:
        show_explanation(st.session_state["last_explanation"])


def show_history_tab(user: dict, session: Session) -> None:
    is_admin = user["role"] == "admin"
    records = list_analyses(session, None if is_admin else user["id"])
    st.subheader("Saved analyses")
    st.caption(
        "Admin view: saved analyses from all users."
        if is_admin
        else "Your logs are private to your account."
    )
    if not records:
        st.info("No saved analyses yet.")
        return
    for record in records:
        result = record.explanation
        with st.expander(
            f"{result['category'].replace('_', ' ').title()} — {result['summary']}"
        ):
            st.caption(
                f"User: {record.username} · "
                f"Saved: {record.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            show_explanation(result)
            st.markdown("**Saved redacted log excerpt**")
            st.code(record.log, language=None)


def show_account_tab(user: dict, session: Session) -> None:
    st.subheader("Change your password")
    with st.form("change_password_form"):
        current_password = st.text_input("Current password", type="password")
        new_password = st.text_input("New password (at least 12 characters)", type="password")
        submitted = st.form_submit_button("Change password")
    if submitted:
        try:
            changed = change_password(
                session, user["id"], current_password, new_password
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Password changed.") if changed else st.error(
                "Current password is incorrect or the account is inactive."
            )


def show_admin_tab(user: dict, session: Session) -> None:
    st.subheader("Create a user account")
    with st.form("create_user_form"):
        username = st.text_input("New username")
        email = st.text_input("User email address")
        password = st.text_input("Temporary password (at least 12 characters)", type="password")
        submitted = st.form_submit_button("Create user")
    if submitted:
        try:
            create_account(session, username, password, email)
            sent = request_email_verification(
                session, email, os.environ.get("APP_OTP_SECRET", "")
            )
            if sent:
                st.success(
                    f"Account created and a verification code sent to {email.strip()}. "
                    "Share the temporary password securely."
                )
            else:
                st.info(
                    "Account created. A verification email may already be pending; "
                    "ask the user to request a new code from Create account."
                )
        except ValueError as error:
            st.error(str(error))
        except RuntimeError as error:
            st.error(
                f"Account was created but the verification email was not sent: {error}"
            )
        except SQLAlchemyError:
            session.rollback()
            st.error("Could not create the account. Check the MySQL connection.")

    accounts = list_accounts(session)
    st.subheader("Manage user accounts")
    other_accounts = [account for account in accounts if account.id != user["id"]]
    if other_accounts:
        username = st.selectbox("Select an account", [a.username for a in other_accounts])
        selected = next(a for a in other_accounts if a.username == username)
        with st.form("reset_password_form"):
            new_password = st.text_input("Reset password", type="password")
            reset = st.form_submit_button("Reset password")
        if reset:
            try:
                if reset_password(session, selected.id, new_password):
                    st.success("Password reset. Share the temporary password securely.")
                else:
                    st.error("Account is no longer active.")
            except ValueError as error:
                st.error(str(error))
        if not selected.email_verified and st.button(
            "Send email verification code", key=f"verify_{selected.id}"
        ):
            try:
                sent = request_email_verification(
                    session, selected.email or "", os.environ.get("APP_OTP_SECRET", "")
                )
                if sent:
                    st.success("Verification code sent.")
                else:
                    st.info("Please wait before requesting another code.")
            except RuntimeError as error:
                st.error(str(error))
        action = "Disable account" if selected.active else "Enable account"
        if st.button(action, key=f"toggle_{selected.id}"):
            try:
                set_account_active(
                    session, selected.id, not selected.active, user["id"]
                )
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    st.subheader("All user accounts")
    st.dataframe(
        [
            {
                "Username": a.username,
                "Email": a.email or "",
                "Email verified": a.email_verified,
                "Role": a.role,
                "Active": a.active,
            }
            for a in accounts
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("All saved analyses")
    for record in list_analyses(session):
        with st.expander(f"{record.username} — {record.explanation['summary']}"):
            st.caption(record.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
            show_explanation(record.explanation)
            st.code(record.log, language=None)


def main() -> None:
    st.set_page_config(page_title="CI Failure Explainer", page_icon="🔎", layout="wide")
    st.title("CI Failure Explainer")
    st.caption("Evidence-backed CI failure analysis with private user accounts.")

    mysql_host = os.environ.get("MYSQL_HOST", "127.0.0.1").strip()
    mysql_port = int(os.environ.get("MYSQL_PORT", "3306"))
    mysql_user = os.environ.get("MYSQL_USER", "").strip()
    mysql_password = os.environ.get("MYSQL_PASSWORD", "")
    mysql_database = os.environ.get("MYSQL_DATABASE", "ci_failure_explainer").strip()
    if not mysql_user or not mysql_password:
        st.error("MySQL is not configured. Set MYSQL_USER and MYSQL_PASSWORD in .env.")
        st.code(
            "1. Install and start MySQL Server on this computer.\n"
            "2. Create the ci_failure_explainer database and an app database user.\n"
            "3. Set MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD and MYSQL_DATABASE in .env.\n"
            "4. Set CI_ADMIN_USERNAME and a strong CI_ADMIN_PASSWORD in .env.\n"
            "5. Restart this app."
        )
        return

    try:
        url = URL.create(
            "mysql+mysqlconnector",
            username=mysql_user,
            password=mysql_password,
            host=mysql_host,
            port=mysql_port,
            database=mysql_database,
        )
        engine = get_engine(url)
        initialize_database(engine)
        with Session(engine) as session:
            if not ensure_bootstrap_admin(
                session,
                os.environ.get("CI_ADMIN_USERNAME", ""),
                os.environ.get("CI_ADMIN_PASSWORD", ""),
                os.environ.get("CI_ADMIN_EMAIL", ""),
            ):
                st.error(
                    "Admin email is missing or unverified. Set CI_ADMIN_EMAIL, "
                    "CI_ADMIN_USERNAME, and CI_ADMIN_PASSWORD in .env, then restart."
                )
                return
            if not show_login(session):
                return

            user = st.session_state["auth_user"]
            with st.sidebar:
                st.write(f"Signed in as **{user['username']}** ({user['role']})")
                if st.button("Log out"):
                    st.session_state.pop("auth_user", None)
                    st.session_state.pop("last_explanation", None)
                    st.rerun()
                st.header("Analysis settings")
                api_key = st.text_input(
                    "Anthropic API key",
                    type="password",
                    help="Used for this browser session; it is not saved in MySQL.",
                ).strip()
                has_key = bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))
                mode = st.radio(
                    "Analysis engine",
                    ("Anthropic model", "Rules only"),
                    index=0 if has_key else 1,
                )
                model = st.text_input(
                    "Anthropic model",
                    value=os.environ.get("CI_EXPLAINER_MODEL", "claude-haiku-5-5"),
                    disabled=mode == "Rules only",
                )
                max_tokens = st.number_input(
                    "Maximum response tokens", 1, 8192, 700, step=128,
                    disabled=mode == "Rules only",
                )
                max_upload_mb = st.number_input("Maximum log size (MB)", 1, 200, 10)

            settings = {
                "api_key": api_key,
                "mode": mode,
                "model": model,
                "max_tokens": int(max_tokens),
                "max_upload_mb": int(max_upload_mb),
            }
            names = ["Analyze log", "My history", "Account"]
            if user["role"] == "admin":
                names.append("Admin")
            tabs = st.tabs(names)
            with tabs[0]:
                show_analysis_tab(user, session, settings)
            with tabs[1]:
                show_history_tab(user, session)
            with tabs[2]:
                show_account_tab(user, session)
            if user["role"] == "admin":
                with tabs[3]:
                    show_admin_tab(user, session)
    except SQLAlchemyError as error:
        if "REFERENCES command denied" in str(error):
            st.error(
                "The MySQL app user needs REFERENCES permission to create the analysis "
                "table. Connect as a MySQL administrator in Workbench and run: "
                "GRANT REFERENCES ON ci_failure_explainer.* TO 'ci_app'@'localhost';"
            )
        else:
            st.error(
                "Could not connect to MySQL or initialize the app tables. Check the service, "
                "credentials, database name, and database permissions."
            )
    except ValueError as error:
        st.error(f"Could not initialize the admin account: {error}")


if __name__ == "__main__":
    main()
