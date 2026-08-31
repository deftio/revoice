from revoice.core.preflight import build_plan

MIXED = (
    "# Notes\n\nThe output impedance stays below 50 Ω with 3.3 V ± 0.05 V at 12 kHz. "
    "V_out = V_in * R2/(R1+R2). See Smith et al., 2019.\n\n"
    '"Not again," she said, setting down the iron. "It always does this."\n\n'
    "- order parts\n- check https://example.com/x.pdf\n"
)


def test_plan_is_deterministic_and_llm_free():
    p1, p2 = build_plan(MIXED), build_plan(MIXED)
    assert p1 == p2


def test_detectors():
    p = build_plan(MIXED)
    assert p["densities"]["math"] > 1
    assert p["densities"]["dialogue"] > 0
    assert p["densities"]["citations"] > 0
    assert p["densities"]["urls"] > 0
    treatments = [s["treatment"] for s in p["segments"]]
    assert "revoice" in treatments
    cautions = [c for s in p["segments"] for c in s.get("cautions", [])]
    assert any("math-dense" in c for c in cautions)
    assert any("URL" in c for c in cautions)


def test_chunking_seams_for_large_docs():
    big = ("A paragraph of ordinary prose that continues for a while.\n\n" * 300)
    p = build_plan(big)
    assert p["chunking"]["needed"]
    assert len(p["chunking"]["seams"]) >= 1
    assert all(0 < s < len(big) for s in p["chunking"]["seams"])


def test_stats_and_segments_blend():
    p = build_plan(MIXED)
    assert p["doc_kind"]
    assert abs(sum(p["blend"].values()) - 1.0) < 0.05
