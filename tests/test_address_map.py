"""Contract 4: address_map.yaml -> uio_config.dts.

Verifies:
* generated .dts is deterministic (regen idempotent)
* validation catches address overlap + IRQ collisions
* committed uio_config.dts in sw/driver/ matches gen_dts.py output
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.ci.gen_dts import generate, render, _validate, _load, main as gen_main


REPO_ROOT = Path(__file__).resolve().parent.parent
ADDR_MAP = REPO_ROOT / "hw" / "vivado" / "out" / "address_map.yaml"
DTS_PATH = REPO_ROOT / "sw" / "driver" / "uio_config.dts"


@pytest.mark.contract
class TestRender:
    def test_render_deterministic(self):
        spec = _load(ADDR_MAP)
        a = render(spec)
        b = render(spec)
        assert a == b
        # also: starts with the auto-generated banner
        assert a.startswith("/*")

    def test_render_sorts_by_address(self):
        """Peripherals must be emitted in ascending base order."""
        spec = _load(ADDR_MAP)
        text = render(spec)
        # find offset of each peripheral name in text
        peri = spec["peripherals"]
        positions = [(int(p["base"]), name, text.find(f"{name}:")) for name, p in peri.items()]
        positions.sort()  # by base
        text_positions = [pos for _, _, pos in positions]
        assert text_positions == sorted(text_positions), \
            "peripheral lines must appear in ascending base address order"


@pytest.mark.contract
class TestValidate:
    def test_valid_baseline(self):
        spec = _load(ADDR_MAP)
        assert _validate(spec) == []

    def test_catches_address_overlap(self):
        spec = {
            "peripherals": {
                "a": {"base": 0x43C00000, "size": 0x20000, "irq": 61},
                "b": {"base": 0x43C10000, "size": 0x10000, "irq": 62},   # overlaps a
            }
        }
        errs = _validate(spec)
        assert any("overlap" in e for e in errs), errs

    def test_catches_irq_collision(self):
        spec = {
            "peripherals": {
                "a": {"base": 0x43C00000, "size": 0x10000, "irq": 61},
                "b": {"base": 0x43C10000, "size": 0x10000, "irq": 61},
            }
        }
        errs = _validate(spec)
        assert any("irq" in e and "61" in e for e in errs), errs

    def test_irq_out_of_range(self):
        spec = {
            "peripherals": {
                "a": {"base": 0x43C00000, "size": 0x10000, "irq": 30},
            }
        }
        errs = _validate(spec)
        assert any("PL range" in e for e in errs), errs


@pytest.mark.contract
class TestGenerate:
    def test_generate_idempotent(self, tmp_path):
        out_a = tmp_path / "a.dts"
        out_b = tmp_path / "b.dts"
        assert generate(ADDR_MAP, out_a) == []
        assert generate(ADDR_MAP, out_b) == []
        assert out_a.read_bytes() == out_b.read_bytes()

    def test_committed_dts_matches_generator(self, tmp_path):
        """If the .dts is committed, regen output must match byte-for-byte."""
        if not DTS_PATH.exists():
            pytest.skip("uio_config.dts not yet committed — generated below")
        fresh = tmp_path / "fresh.dts"
        assert generate(ADDR_MAP, fresh) == []
        committed = DTS_PATH.read_bytes()
        regen = fresh.read_bytes()
        if committed != regen:
            pytest.fail(
                "sw/driver/uio_config.dts is stale. Re-run:\n"
                f"  python tools/ci/gen_dts.py --addr-map {ADDR_MAP} --output {DTS_PATH}\n"
            )

    def test_no_crlf_in_output(self, tmp_path):
        """Output must be LF-only so Linux device tree compiler is happy."""
        out = tmp_path / "x.dts"
        assert generate(ADDR_MAP, out) == []
        assert b"\r\n" not in out.read_bytes()


@pytest.mark.contract
def test_cli_check_mode(tmp_path):
    """CLI --check mode must succeed against the freshly generated dts."""
    out = tmp_path / "x.dts"
    assert gen_main(["--addr-map", str(ADDR_MAP), "--output", str(out)]) == 0
    assert gen_main(["--addr-map", str(ADDR_MAP), "--output", str(out), "--check"]) == 0
