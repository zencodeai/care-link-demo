-- Additive, explicit review-only capability; existing runs and audit remain.
ALTER TABLE core.review_run DROP CONSTRAINT review_run_scenario_check;
ALTER TABLE core.review_run ADD CONSTRAINT review_run_scenario_check
 CHECK(scenario IN ('manual-service','plans-consent-directory'));
ALTER TABLE core.review_draft DROP CONSTRAINT review_draft_kind_check;
ALTER TABLE core.review_draft ADD CONSTRAINT review_draft_kind_check
 CHECK(kind IN ('intake','message','plan'));
