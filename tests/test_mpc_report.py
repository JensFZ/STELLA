from core.mpc_report import MPCObservation, format_mpc_line, write_mpc_report

SAMPLE = MPCObservation(
    ra_deg=350.4625,  # 23h 21m 51.0s
    dec_deg=-5.5,  # -05 30 00.0
    obs_time="2026-03-15T06:12:00",
    magnitude=19.3,
    band="V",
    designation="K26A00A",
    observatory_code="500",
)


def test_format_mpc_line_has_correct_length():
    line = format_mpc_line(SAMPLE)

    assert len(line) == 80


def test_format_mpc_line_contains_expected_fields():
    line = format_mpc_line(SAMPLE)

    assert line[5:12] == "K26A00A"
    assert line[15:32] == "2026 03 15.258333"
    assert line[32:44] == "23 21 51.00 "
    assert line[44:56] == "-05 30 00.0 "
    assert line[65:70] == " 19.3"
    assert line[70] == "V"
    assert line[77:80] == "500"


def test_format_mpc_line_handles_missing_magnitude():
    obs = MPCObservation(ra_deg=0.0, dec_deg=0.0, obs_time="2026-01-01T00:00:00", magnitude=None)

    line = format_mpc_line(obs)

    assert len(line) == 80
    assert line[65:70] == "     "


def test_write_mpc_report_creates_file_with_one_line_per_observation(tmp_path):
    out_path = tmp_path / "report.txt"

    write_mpc_report([SAMPLE, SAMPLE], out_path)

    content = out_path.read_text(encoding="ascii")
    lines = content.splitlines()
    assert len(lines) == 2
    assert all(len(line) == 80 for line in lines)
