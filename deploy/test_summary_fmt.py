from call_qc import format_day_summary

print(
    format_day_summary(
        "2026-07-22",
        0,
        0,
        3,
        0,
        0,
        site_label="SOCO Moscow",
        stats_unavailable=True,
    )
)
print("---")
print(
    format_day_summary(
        "2026-07-22",
        5,
        1,
        3,
        0,
        0,
        site_label="SOCO Moscow",
        stats_unavailable=False,
    )
)
