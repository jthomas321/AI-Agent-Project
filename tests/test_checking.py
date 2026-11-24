from agents.checking_agent import check

def test_verified_when_source_supports_fields(dessert):
    assert check([dessert()])[0]["check"]["status"] == "verified"

def test_price_not_verified_by_checking(dessert):
    result = check([dessert(price=9.0)])[0]["check"]

    assert "price" not in result["flagged_fields"]
    assert "price" not in result["verified_fields"]

def test_flavor_conflict_flagged(dessert):
    result = check([dessert(flavors=["vanilla"])])[0]["check"]
    assert "flavors" in result["flagged_fields"]

def test_no_evidence_unknown(dessert):
    assert check([dessert(evidence=[])])[0]["check"]["status"] == "unknown"

def test_evidence_and_id_preserved(dessert):
    d = dessert("abc")
    result = check([d])[0]
    assert result["dessert"]["evidence"] == d["evidence"]
    assert result["check"]["dessert_id"] == "abc"
