from campusride.demo import run_demo


def test_full_journey_runs_and_reports_expected_milestones():
    log = run_demo()
    assert log[0] == "Registered and verified 2 users"
    assert any(line.startswith("Matches found: 1") for line in log)
    assert any("confirmed, seats left: 2" in line for line in log)
    assert "Chat messages: 1" in log
    assert any("Driver rating: (5.0, 1)" in line for line in log)
