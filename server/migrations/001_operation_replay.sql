-- Add replay request/result storage to an existing schema. Safe to rerun.
BEGIN;

ALTER TABLE canvas_operation
    ADD COLUMN IF NOT EXISTS request jsonb,
    ADD COLUMN IF NOT EXISTS result jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'canvas_operation_request_result_pair_check'
          AND conrelid = 'canvas_operation'::regclass
    ) THEN
        ALTER TABLE canvas_operation
            ADD CONSTRAINT canvas_operation_request_result_pair_check CHECK (
                (request IS NULL AND result IS NULL)
                OR (
                    request IS NOT NULL AND result IS NOT NULL
                    AND jsonb_typeof(request) = 'object'
                    AND jsonb_typeof(result) = 'object'
                )
            );
    END IF;
END
$$;

COMMIT;
