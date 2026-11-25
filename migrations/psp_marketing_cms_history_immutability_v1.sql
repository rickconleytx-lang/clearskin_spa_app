-- Peach Suite Pro Corporate Marketing CMS
-- Protect historical revisions and publication audit events.
-- Apply only after psp_marketing_cms_foundation_v1.sql.
--
-- Current page state remains editable through the CMS service.
-- This migration does not publish or restore content.

BEGIN;

CREATE OR REPLACE FUNCTION
psp_marketing_reject_history_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'Marketing CMS historical records cannot be modified: %',
        TG_TABLE_NAME
        USING ERRCODE = '23514';

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS
    trg_psp_marketing_revisions_immutable
    ON psp_marketing_revisions;

CREATE TRIGGER
    trg_psp_marketing_revisions_immutable
BEFORE UPDATE OR DELETE
ON psp_marketing_revisions
FOR EACH ROW
EXECUTE FUNCTION
    psp_marketing_reject_history_mutation();

DROP TRIGGER IF EXISTS
    trg_psp_marketing_publications_immutable
    ON psp_marketing_publication_events;

CREATE TRIGGER
    trg_psp_marketing_publications_immutable
BEFORE UPDATE OR DELETE
ON psp_marketing_publication_events
FOR EACH ROW
EXECUTE FUNCTION
    psp_marketing_reject_history_mutation();

COMMIT;
