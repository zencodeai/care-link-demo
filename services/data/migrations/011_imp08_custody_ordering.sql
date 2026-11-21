-- Current custody writers share the gateway's first lock. This serializes boot,
-- reviewer, receipt and privilege changes with final checks through commit;
-- the runtime still has no UPDATE privilege on the custody registries.
CREATE FUNCTION governance.order_custody_change() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,control AS $$
BEGIN
 PERFORM 1 FROM control.guard WHERE key='demo' FOR UPDATE;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION governance.order_custody_change() FROM PUBLIC;

CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.instance FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.human_registry FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.approval FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.signer FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.candidate FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.exception_rule FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON governance.review FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
CREATE TRIGGER order_custody_change BEFORE INSERT OR UPDATE OR DELETE
 ON control.principal_guard FOR EACH STATEMENT EXECUTE FUNCTION governance.order_custody_change();
