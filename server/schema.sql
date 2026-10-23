-- Docker Compose reapplies this idempotent base schema on startup.
BEGIN;

CREATE TABLE IF NOT EXISTS app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_user_username_normalized_check
        CHECK (username = lower(btrim(username)) AND btrim(username) <> ''),
    CONSTRAINT app_user_password_hash_nonempty_check
        CHECK (btrim(password_hash) <> '')
);

CREATE TABLE IF NOT EXISTS auth_session (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CONSTRAINT auth_session_token_hash_nonempty_check CHECK (btrim(token_hash) <> ''),
    CONSTRAINT auth_session_expiry_check CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS canvas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL,
    created_by uuid NOT NULL REFERENCES app_user (id),
    revision bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT canvas_title_nonempty_check CHECK (btrim(title) <> ''),
    CONSTRAINT canvas_revision_nonnegative_check CHECK (revision >= 0)
);

CREATE TABLE IF NOT EXISTS canvas_member (
    canvas_id uuid NOT NULL REFERENCES canvas (id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    joined_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (canvas_id, user_id)
);

CREATE TABLE IF NOT EXISTS canvas_invitation (
    canvas_id uuid NOT NULL REFERENCES canvas (id) ON DELETE CASCADE,
    invitee_id uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    invited_by uuid NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (canvas_id, invitee_id)
);

CREATE TABLE IF NOT EXISTS shape (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_id uuid NOT NULL REFERENCES canvas (id) ON DELETE CASCADE,
    kind text NOT NULL,
    properties jsonb NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT shape_kind_check CHECK (kind IN ('rectangle', 'ellipse', 'line', 'text')),
    CONSTRAINT shape_properties_object_check CHECK (jsonb_typeof(properties) = 'object'),
    CONSTRAINT shape_revision_positive_check CHECK (revision > 0),
    CONSTRAINT shape_id_canvas_id_key UNIQUE (id, canvas_id)
);

CREATE TABLE IF NOT EXISTS canvas_operation (
    id uuid PRIMARY KEY,
    canvas_id uuid NOT NULL REFERENCES canvas (id) ON DELETE CASCADE,
    shape_id uuid NOT NULL,
    actor_id uuid NOT NULL REFERENCES app_user (id),
    canvas_revision bigint NOT NULL,
    kind text NOT NULL,
    before_patch jsonb NOT NULL DEFAULT '{}'::jsonb,
    after_patch jsonb NOT NULL DEFAULT '{}'::jsonb,
    request jsonb,
    result jsonb,
    target_operation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT canvas_operation_shape_canvas_fkey
        FOREIGN KEY (shape_id, canvas_id) REFERENCES shape (id, canvas_id),
    CONSTRAINT canvas_operation_target_canvas_fkey
        FOREIGN KEY (target_operation_id, canvas_id)
        REFERENCES canvas_operation (id, canvas_id),
    CONSTRAINT canvas_operation_revision_positive_check CHECK (canvas_revision > 0),
    CONSTRAINT canvas_operation_kind_check
        CHECK (kind IN ('create', 'update', 'delete', 'undo', 'redo')),
    CONSTRAINT canvas_operation_before_patch_object_check
        CHECK (jsonb_typeof(before_patch) = 'object'),
    CONSTRAINT canvas_operation_after_patch_object_check
        CHECK (jsonb_typeof(after_patch) = 'object'),
    CONSTRAINT canvas_operation_request_result_pair_check CHECK (
        (request IS NULL AND result IS NULL)
        OR (
            request IS NOT NULL AND result IS NOT NULL
            AND jsonb_typeof(request) = 'object'
            AND jsonb_typeof(result) = 'object'
        )
    ),
    CONSTRAINT canvas_operation_canvas_revision_key UNIQUE (canvas_id, canvas_revision),
    CONSTRAINT canvas_operation_id_canvas_id_key UNIQUE (id, canvas_id)
);

CREATE INDEX IF NOT EXISTS canvas_member_user_canvas_idx
    ON canvas_member (user_id, canvas_id);

CREATE INDEX IF NOT EXISTS canvas_invitation_invitee_created_idx
    ON canvas_invitation (invitee_id, created_at DESC);

CREATE INDEX IF NOT EXISTS shape_visible_canvas_idx
    ON shape (canvas_id) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS canvas_operation_actor_revision_idx
    ON canvas_operation (canvas_id, actor_id, canvas_revision DESC);

COMMIT;
