#!/usr/bin/env python3
"""
interface_devkit.py — peri.xml for the BRAM-ring miner on the Titanium
Ti375 N1156 Development Kit (PCIe card, 12 V supply -- no USB power budget).

Board wiring:
  uart_tx  -> AC9 (GPIOL_23, board net UART_TXD -- the net names are from the
              FPGA's perspective, NOT the FTDI's). CONFIRMED on hardware
              2026-07-13 with a hello-spammer bitstream: AC9 -> /dev/ttyUSB2
              (FT4232H interface 2) at 115200; AE10 (net UART_RXD) is silent.
  led_g    -> N6  (LED1, bank 4B, 1.8 V)      led_b -> M4 (LED2)
  uart_rts_n (PLL lock indicator) -> M3 (LED3) -- no FTDI modem line here,
              so lock is a lamp instead of a host-readable signal.
  refclk   -> 33.3333 MHz osc on GPIOR_145 via PLL_BR1 ext_refclk_no=1
              (hardware-proven on this board).

PLL_MHZ is REQUIRED (no native-clock fallback: the osc ball for a plain GPIO
clock input differs on this board and only the PLL path is proven here).
"""
import os, sys
pt_home = os.environ.get('EFXPT_HOME', os.environ.get('EFINITY_HOME', '') + '/pt')
sys.path.append(pt_home + "/bin")
from api_service.design import DesignAPI
from api_service.device import DeviceAPI
import api_service.excp.design_excp as APIExcp

DEVICE  = "Ti375N1156"
PROJECT = "devkit_miner"
IOSTD_33 = "3.3 V LVCMOS"
IOSTD_18 = "1.8 V LVCMOS"
REFCLK_MHZ = 33.3333
PLL_MHZ = os.environ.get("PLL_MHZ")

OUTPUTS = {
    "uart_tx":    ("AC9",  IOSTD_33),   # GPIOL_23, net UART_TXD (hw-confirmed)
    "led_g":      ("N6",   IOSTD_18),   # LED1
    "led_b":      ("M4",   IOSTD_18),   # LED2
    "uart_rts_n": ("M3",   IOSTD_18),   # LED3 = PLL lock lamp
}

def main():
    if not PLL_MHZ:
        print("PLL_MHZ is required for the devkit build", file=sys.stderr)
        sys.exit(1)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    design = DesignAPI(is_verbose=True)
    _      = DeviceAPI(is_verbose=True)
    design.create(PROJECT, DEVICE, out_dir)

    for name, (ball, iostd) in OUTPUTS.items():
        design.create_output_gpio(name)
        design.set_property(name, "IO_STANDARD", iostd)
        design.assign_pkg_pin(name, ball)

    # ---- PLL: GPIOR_145 33.33 MHz refclk -> CLKOUT1 = clk @ PLL_MHZ ----
    f = float(PLL_MHZ)
    design.create_block("pll0", block_type="PLL")
    design.gen_pll_ref_clock("pll0", pll_res="PLL_BR1", refclk_src="EXTERNAL",
                             refclk_name="clk_ref", ext_refclk_no="1")
    design.set_property("clk_ref", "IO_STANDARD", IOSTD_33)
    design.set_property("pll0", {
        "REFCLK_FREQ": str(REFCLK_MHZ),
        "CLKOUT0_EN": "1", "CLKOUT0_PIN": "clk0_unused",
        "CLKOUT1_EN": "1", "CLKOUT1_PIN": "clk",
        "LOCKED_PIN": "pll_locked",
    }, block_type="PLL")
    # auto_calc picks the PLL's internal dividers for a requested output; ask
    # it for 250 MHz to lock the VCO at 4000, then override CLKOUT1_DIV so the
    # actual output lands on PLL_MHZ = VCO/DIV exactly (auto_calc alone won't
    # hit arbitrary frequencies).
    design.auto_calc_pll_clock("pll0", target_freq={
        "CLKOUT0_FREQ": "100.0", "CLKOUT1_FREQ": "250.0"})
    vco = float(design.get_property("pll0", ["VCO_FREQ"], block_type="PLL")["VCO_FREQ"])
    div1 = max(2, round(vco / f))
    design.set_property("pll0", {"CLKOUT1_DIV": str(div1)}, block_type="PLL")
    got = design.get_property("pll0", ["VCO_FREQ", "CLKOUT1_FREQ", "CLKOUT1_DIV"],
                              block_type="PLL")
    print(f"[interface_devkit.py] PLL VCO={vco:.0f} div1={div1} -> {got}")

    try:
        design.generate(enable_bitstream=False)
    except APIExcp.PTDsgCheckException as e:
        print(f"Design check failed: {e.get_msg()}", file=sys.stderr); sys.exit(1)
    design.save()
    print(f"[interface_devkit.py] wrote {out_dir}/{PROJECT}.peri.xml (PLL {PLL_MHZ} MHz)")

if __name__ == "__main__":
    main()
