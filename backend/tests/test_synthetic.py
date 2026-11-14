from app.services.synthetic import generate_synthetic_month


def test_synthetic_month():
    records = generate_synthetic_month(count=100)

    assert len(records) == 100
    assert len(set(r.call_id for r in records)) == 100
    assert all(r.call_id.startswith("SYN-") for r in records)