WITH ranked_shapes AS (
    SELECT id, row_number() OVER (PARTITION BY canvas_id ORDER BY id) - 1 AS z_index
    FROM shape
)
UPDATE shape
SET properties = jsonb_set(
    jsonb_set(
        properties,
        '{opacity}',
        COALESCE(properties->'opacity', '1'::jsonb),
        true
    ),
    '{z_index}',
    COALESCE(properties->'z_index', to_jsonb(ranked_shapes.z_index)),
    true
)
FROM ranked_shapes
WHERE shape.id = ranked_shapes.id
  AND (NOT (properties ? 'opacity') OR NOT (properties ? 'z_index'));
