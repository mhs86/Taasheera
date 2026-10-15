"""Private SQL reporting view, accessible only through administrative DB access."""

ADMIN_USER_VIEW = """
CREATE VIEW admin_user_auth AS
SELECT t.id, t.name, t.email, t.sso_email, t.auth_type,
       CASE WHEN t.password_hash <> '' AND t.auth_type = 'email_password' THEN 1 ELSE 0 END AS password_enabled,
       CASE WHEN EXISTS (SELECT 1 FROM googleidentity g WHERE g.traveler_id = t.id) THEN 1 ELSE 0 END AS google_enabled,
       t.last_login_method, t.last_login_at
FROM traveler t
"""
