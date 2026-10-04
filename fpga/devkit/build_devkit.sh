#!/bin/bash
# Ti375 devkit build: the miner that produced the README's measured number
# (2 rings @ 95 MHz on the Efinix Titanium Ti375N1156 Development Kit).
#
#   NRINGS=2 CLKDIV=1 PLL_MHZ=95 ./build_devkit.sh build
#   ./build_devkit.sh program     # volatile JTAG load (gone at power-off)
#   ./build_devkit.sh clean
#
# Programming is a VOLATILE SRAM load: it replaces whatever design the board
# is running until the next power cycle and never touches the SPI flash.
# It loads the .bit (never the .hex — that leaves CDONE=0) over the devkit's
# JTAG on FTDI channel B (the "/2" in the programmer URL). A wrong channel
# "succeeds" while reading IDCODE 0xFFFFFFFF, so trust the UART, not the
# programmer's exit message:  python3 ../read_miner.py --port /dev/ttyUSB2
set -e
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # .../bram-ring/fpga/devkit
REPO="$(cd "$SD/../.." && pwd)"                         # .../bram-ring
: "${EFINITY_HOME:?source <efinity>/bin/setup.sh first}"
EFX_RUN="$EFINITY_HOME/bin/efx_run"

PROJECT="devkit_miner"; TOP="miner_top"
DEVICE="Ti375N1156"; FAMILY="Titanium"; TIMING="C4"
NRINGS="${NRINGS:-2}"; CLKDIV="${CLKDIV:-1}"; SEED="${SEED:-1}"
OUTFLOW="$SD/outflow"
G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m'

gather_rtl() {
    ( cd "$REPO" && env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE \
        make -s gen PY=/usr/bin/python3 )               # regenerate from spec.py
    cp "$REPO/fpga/ring.v"     "$SD/ring.v"
    cp "$REPO/fpga/top.v"      "$SD/top.v"              # board-agnostic wrapper
    cp "$REPO/fpga/miner.v"    "$SD/miner.v"
    cp "$REPO/fpga/uart_tx.v"  "$SD/"
    cp "$REPO/fpga/params.vh"  "$SD/params.vh"
    cp "$REPO/fpga/prev256.vh" "$SD/prev256.vh"
    cp "$REPO/fpga/epoch.vh"   "$SD/epoch.vh"
}

gen_project_xml() {
    local files=""
    for f in top.v ring.v miner.v uart_tx.v; do
        files+="        <efx:design_file name=\"$f\" version=\"default\" library=\"default\"/>\n"
    done
    cat > "$SD/${PROJECT}.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<efx:project name="$PROJECT" description="BRAM-ring miner on $DEVICE devkit" last_change="0" sw_version="2025.2" last_run_state="" last_run_flow="" config_result_in_sync="true" design_ood="sync" place_ood="sync" route_ood="sync" xmlns:efx="http://www.efinixinc.com/enf_proj" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.efinixinc.com/enf_proj enf_proj.xsd">
    <efx:device_info>
        <efx:family name="$FAMILY"/>
        <efx:device name="$DEVICE"/>
        <efx:timing_model name="$TIMING"/>
    </efx:device_info>
    <efx:design_info def_veri_version="verilog_2k" def_vhdl_version="vhdl_2008">
        <efx:top_module name="$TOP"/>
$(printf "$files")        <efx:top_vhdl_arch name=""/>
    </efx:design_info>
    <efx:constraint_info>
        <efx:sdc_file name="combined.sdc"/>
        <efx:inter_file name=""/>
    </efx:constraint_info>
    <efx:sim_info/><efx:misc_info/><efx:ip_info/>
    <efx:synthesis tool_name="efx_map">
        <efx:param name="work_dir" value="work_syn" value_type="e_string"/>
        <efx:param name="write_efx_verilog" value="on" value_type="e_bool"/>
        <efx:param name="mode" value="speed" value_type="e_option"/>
    </efx:synthesis>
    <efx:place_and_route tool_name="efx_pnr">
        <efx:param name="work_dir" value="work_pnr" value_type="e_string"/>
        <efx:param name="optimization_level" value="TIMING_3" value_type="e_option"/>
        <efx:param name="seed" value="$SEED" value_type="e_integer"/>
        <efx:param name="max_threads" value="-1" value_type="e_integer"/>
    </efx:place_and_route>
    <efx:bitstream_generation tool_name="efx_pgm">
        <efx:param name="mode" value="active" value_type="e_option"/>
        <efx:param name="width" value="1" value_type="e_option"/>
        <efx:param name="generate_bit" value="on" value_type="e_bool"/>
        <efx:param name="generate_hex" value="off" value_type="e_bool"/>
    </efx:bitstream_generation>
</efx:project>
EOF
}

do_build() {
    echo -e "${Y}=== build $TOP on $DEVICE devkit: PLL ${PLL_MHZ:-?} MHz NRINGS=$NRINGS CLKDIV=$CLKDIV seed=$SEED ===${N}"
    cd "$SD"
    : "${PLL_MHZ:?PLL_MHZ required (e.g. PLL_MHZ=95)}"
    gather_rtl
    rm -f "$SD/${PROJECT}.peri.xml" "$SD/${PROJECT}.pt.sdc" "$SD/combined.sdc"
    gen_project_xml      # BEFORE the interface step: the vendor API reads the project
                         # file as it creates the design and otherwise prints
                         # "File error : Efinity project file does not exists" seven times
    PLL_MHZ="$PLL_MHZ" "$EFINITY_HOME/bin/python3" "$SD/interface_devkit.py"
    local ptsdc="$SD/${PROJECT}.pt.sdc"; [ -f "$OUTFLOW/${PROJECT}.pt.sdc" ] && ptsdc="$OUTFLOW/${PROJECT}.pt.sdc"
    [ -f "$ptsdc" ] || { echo -e "${R}no pt.sdc from interface (PLL clk undefined)${N}"; exit 1; }
    { cat "$ptsdc"; echo "create_clock -name clk_ref -period 30.000 [get_ports {clk_ref}]"; } > "$SD/combined.sdc"
    printf '`define PLL\n`define PLL_CLK_HZ %d\n' "$(( ${PLL_MHZ%%.*} * 1000000 ))" > "$SD/miner_defs.vh"
    printf '`define NRINGS %d\n`define CLKDIV %d\n' "$NRINGS" "$CLKDIV" >> "$SD/miner_defs.vh"
    mkdir -p "$OUTFLOW"
    rm -f "$OUTFLOW/${PROJECT}.bit" "$OUTFLOW/${PROJECT}.timing.rpt"   # never grade a leftover
    "$EFX_RUN" --prj "$SD/${PROJECT}.xml" -f compile
    local bit="$OUTFLOW/${PROJECT}.bit"
    [ -f "$bit" ] || { echo -e "${R}no fresh .bit — stage FAILED (efx_run exit 0 lies)${N}"; exit 1; }
    echo -e "${G}BUILD OK${N}: $bit"
    grep -E "EFX-0201|VDB-1002" "$OUTFLOW"/*.log work_syn/*.log 2>/dev/null && echo -e "${R}^^ GND-rewire hits — INVESTIGATE${N}" || echo "gnd-rewire grep clean"
    grep -i "tied off" "$OUTFLOW"/*map* work_syn/*.rpt 2>/dev/null | head -3 || true
    grep -A4 "Maximum possible analyzed clocks frequency" "$OUTFLOW/${PROJECT}.timing.rpt" | head -8
}

do_program() {
    local bit="$OUTFLOW/${PROJECT}.bit"
    [ -f "$bit" ] || { echo -e "${R}build first${N}"; exit 1; }
    local busaddr
    busaddr=$(lsusb -d 0403:6011 | sed -E 's/Bus 0*([0-9]+) Device 0*([0-9]+).*/\1:\2/')
    [ -n "$busaddr" ] || { echo -e "${R}devkit (FTDI 0403:6011) not on USB${N}"; exit 1; }
    echo -e "${Y}volatile JTAG load (FTDI ch B)...${N}"
    env -u PYTHONHOME -u PYTHONPATH "$EFINITY_HOME/bin/python3" \
        "$EFINITY_HOME/pgm/bin/efx_pgm/ftdi_program.py" -m jtag \
        -b "Generic Board Profile Using FT4232" \
        -u "ftdi://0x0403:0x6011:${busaddr}/2" "$bit" 2>&1 | tail -2
    echo -e "${G}loaded (volatile — a power cycle restores whatever is in flash).${N}"
    echo "read the miner:  python3 $REPO/fpga/read_miner.py --port /dev/ttyUSB2"
}

do_clean() { cd "$SD"; rm -rf outflow work_syn work_pnr work_pt work_dbg; rm -f ${PROJECT}.xml ${PROJECT}.peri.xml *.log ring.v miner.v top.v uart_tx.v epoch.vh params.vh prev256.vh miner_defs.vh combined.sdc; echo -e "${G}clean${N}"; }

case "${1:-build}" in
    build) do_build ;; program) do_program ;; all) do_build; do_program ;; clean) do_clean ;;
    *) echo "unknown: $1"; exit 1 ;;
esac
