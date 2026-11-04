-- Run interactively as schema owner after migrations, on the intended database.
-- No credential is stored here. psql prompts for the new role's password.
CREATE ROLE islamcar_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password islamcar_app
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE islamcar TO islamcar_app;
GRANT USAGE ON SCHEMA public TO islamcar_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO islamcar_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO islamcar_app;
ALTER DEFAULT PRIVILEGES FOR ROLE islamcar IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO islamcar_app;
ALTER DEFAULT PRIVILEGES FOR ROLE islamcar IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO islamcar_app;
