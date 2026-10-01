"""PostgreSQL constraints shared by persisted media execution summaries."""

_REFERENCE = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_IPV4_OCTET = "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = rf"^({_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}$"


def execution_context_check(document: str) -> str:
    """Reject incomplete, extra or sensitive fields while allowing no context."""
    fields = (
        "provider_key",
        "registry_revision",
        "resolved_layer",
        "client",
        "engine_revision",
        "egress_route",
        "egress_revision",
        "egress_class",
        "egress_observed_ip",
        "identity_used",
        "identity_digest",
        "browser_context_kind",
    )
    keys = "ARRAY[" + ",".join(f"'{key}'" for key in fields) + "]::text[]"
    references = (
        "provider_key",
        "registry_revision",
        "client",
        "engine_revision",
        "egress_route",
        "egress_revision",
    )
    checks = [
        f"{document} ?& {keys}",
        f"({document} - {keys}) = '{{}}'::jsonb",
        *(
            f"jsonb_typeof({document}->'{key}') = 'string' AND "
            f"{document}->>'{key}' ~ '{_REFERENCE}'"
            for key in references
        ),
        f"jsonb_typeof({document}->'resolved_layer') = 'string' AND "
        f"{document}->>'resolved_layer' IN ('L1','L2','L3')",
        f"jsonb_typeof({document}->'egress_class') = 'string' AND "
        f"{document}->>'egress_class' IN ('unknown','residential','datacenter')",
        f"({document}->'egress_observed_ip' = 'null'::jsonb OR "
        f"(jsonb_typeof({document}->'egress_observed_ip') = 'string' AND "
        f"{document}->>'egress_observed_ip' !~ '[/%]' AND "
        f"({document}->>'egress_observed_ip' LIKE '%:%' OR "
        f"{document}->>'egress_observed_ip' ~ '{_IPV4}') AND "
        f"pg_input_is_valid({document}->>'egress_observed_ip', 'inet')))",
        f"jsonb_typeof({document}->'identity_used') = 'boolean'",
        f"(({document}->'identity_used' = 'false'::jsonb AND "
        f"{document}->'identity_digest' = 'null'::jsonb) OR "
        f"({document}->'identity_used' = 'true'::jsonb AND "
        f"jsonb_typeof({document}->'identity_digest') = 'string' AND "
        f"{document}->>'identity_digest' ~ '{_REFERENCE}'))",
        f"jsonb_typeof({document}->'browser_context_kind') = 'string' AND "
        f"({document}->>'browser_context_kind' = 'none' OR "
        f"({document}->>'resolved_layer' = 'L3' AND "
        f"(({document}->>'browser_context_kind' = 'anonymous' AND "
        f"{document}->'identity_used' = 'false'::jsonb) OR "
        f"({document}->>'browser_context_kind' = 'authenticated' AND "
        f"{document}->'identity_used' = 'true'::jsonb))))",
    ]
    predicates = " AND ".join(f"({check})" for check in checks)
    return (
        f"CASE WHEN {document} IS NULL THEN TRUE "
        f"WHEN jsonb_typeof({document}) = 'object' THEN "
        f"COALESCE({predicates}, FALSE) ELSE FALSE END"
    )
