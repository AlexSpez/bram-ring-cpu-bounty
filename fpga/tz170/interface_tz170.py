#!/usr/bin/env python3
"""
interface_tz170.py — peri.xml for the Topaz (Tz170J484) miner build
(Tz170J484). NO PLL: `clk` is a plain input GPIO on J22 (the devkit's 25 MHz
osc / refclk ball — clock-capable), the v1-proven direct-clock pattern; fmax
comes from STA against the SDC target, not from silicon. Outputs ride the
devkit LED balls (E1/F1) + C2 for uart_tx. Bank setup mirrors the vendor
Tz170J484_kit.isf verbatim (numbered banks 1.8 V, corner banks 3.3 V).
"""
import os, sys
pt_home = os.environ.get('EFXPT_HOME', os.environ.get('EFINITY_HOME', '') + '/pt')
sys.path.append(pt_home + "/bin")
from api_service.design import DesignAPI
from api_service.device import DeviceAPI
import api_service.excp.design_excp as APIExcp

DEVICE  = "Tz170J484"
PROJECT = "tz170_miner"

BANKS_18 = ["2A_2B_2C", "3A", "3B_3C", "4A", "4B", "4C"]
BANKS_33 = ["BL", "BR", "TL", "TR"]

PINS_IN  = {"clk": "J22"}
PINS_OUT = {"led_g": "E1", "led_b": "F1", "uart_tx": "C2"}

def setup_bank(design, bank, voltage):
    design.set_device_property(bank, "DYNAMIC_VOLTAGE", "0", "IOBANK")
    design.set_mode_sel_name(bank, f"{bank}_MODE_SEL", bank)
    design.set_device_property(bank, "VOLTAGE", voltage, "IOBANK")

def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    design = DesignAPI(is_verbose=True)
    _      = DeviceAPI(is_verbose=True)
    design.create(PROJECT, DEVICE, out_dir)
    for b in BANKS_18: setup_bank(design, b, "1.8")
    for b in BANKS_33: setup_bank(design, b, "3.3")
    for name, ball in PINS_IN.items():
        design.create_input_gpio(name)
        design.assign_pkg_pin(name, ball)
    for name, ball in PINS_OUT.items():
        design.create_output_gpio(name)
        design.assign_pkg_pin(name, ball)
    try:
        design.generate(enable_bitstream=False)
    except APIExcp.PTDsgCheckException as e:
        print(f"Design check failed: {e.get_msg()}", file=sys.stderr); sys.exit(1)
    design.save()
    print(f"[interface_tz170.py] wrote {out_dir}/{PROJECT}.peri.xml (direct clk on J22)")

if __name__ == "__main__":
    main()
