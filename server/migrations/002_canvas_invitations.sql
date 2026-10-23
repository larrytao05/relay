-- Persist invitations separately until the recipient accepts or declines.
BEGIN;

CREATE TABLE IF NOT EXISTS canvas_invitation (
    canvas_id uuid NOT NULL REFERENCES canvas (id) ON DELETE CASCADE,
    invitee_id uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    invited_by uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (canvas_id, invitee_id)
);

CREATE INDEX IF NOT EXISTS canvas_invitation_invitee_created_idx
    ON canvas_invitation (invitee_id, created_at DESC);

COMMIT;
