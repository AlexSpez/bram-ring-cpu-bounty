#!/bin/bash
# Topaz (Tz170J484) build: one BRAM-ring core, fit + timing characterization.
# on Tz170J484. STA/fit only — there is no Tz board; do NOT add a program step.
#
#   TIMING=C3 TARGET_MHZ=200 NRINGS=1 SEED=1 ./build_tz170.sh build
#   ./build_tz170.sh clean
#
# Grades: C3 (fast) / C2 (slow) / I2 / I3 — Topaz has NO C4; never inherit it.
# Timing tables are Ti180-raw scaled: C3 x1.2075, C2 x1.39 (pt/db/timing_models).
set -e
SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # .../bram-ring/fpga/tz170
REPO="$(cd "$SD/../.." && pwd)"                         # .../bram-ring
: "${EFINITY_HOME:?source <efinity>/bin/setup.sh first}"
EFX_RUN="$EFINITY_HOME/bin/efx_run"

PROJECT="tz170_miner"; TOP="tz170_miner"
DEVICE="Tz170J484"; FAMILY="Topaz"; TIMING="${TIMING:-C3}"
TARGET_MHZ="${TARGET_MHZ:-200}"; NRINGS="${NRINGS:-1}"; SEED="${SEED:-1}"
OUTFLOW="$SD/outflow"
G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m'

gather_rtl() {
    ( cd "$REPO" && env -u PYTHONHOME -u PYTHONPATH -u PYTHONNOUSERSITE \
        make -s gen PY=/usr/bin/python3 )               # -> fpga/{ring.v,*2.vh,prev256.vh}
    sed 's/\bring2\b/ring/g' "$REPO/fpga/ring.v" > "$SD/ring.v"
    # the silicon-proven board wrapper, top renamed to match PROJECT
    sed 's/\bminer_top\b/tz170_miner/g' "$REPO/fpga/top.v" > "$SD/tz170_miner.v"
    cp "$REPO/fpga/miner.v"   "$SD/miner.v"
    cp "$REPO/fpga/uart_tx.v"  "$SD/"
    cp "$REPO/fpga/params.vh" "$SD/params.vh"
    cp "$REPO/fpga/prev256.vh" "$SD/prev256.vh"
    cp "$REPO/fpga/epoch.vh"  "$SD/epoch.vh"
}

gen_project_xml() {
    local files=""
    for f in tz170_miner.v ring.v miner.v uart_tx.v; do
        files+="        <efx:design_file name=\"$f\" version=\"default\" library=\"default\"/>\n"
    done
    cat > "$SD/${PROJECT}.xml" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<efx:project name="$PROJECT" description="BRAM-ring on $DEVICE $TIMING @${TARGET_MHZ} MHz" last_change="0" sw_version="2025.2" last_run_state="" last_run_flow="" config_result_in_sync="true" design_ood="sync" place_ood="sync" route_ood="sync" xmlns:efx="http://www.efinixinc.com/enf_proj" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.efinixinc.com/enf_proj enf_proj.xsd">
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
    echo -e "${Y}=== char build: $TOP on $DEVICE $TIMING, target ${TARGET_MHZ} MHz, NRINGS=$NRINGS seed=$SEED ===${N}"
    cd "$SD"
    gather_rtl
    rm -f "$SD/${PROJECT}.peri.xml" "$SD/${PROJECT}.pt.sdc" "$SD/combined.sdc"
    gen_project_xml      # BEFORE the interface step: the vendor API reads the project
                         # file as it creates the design and otherwise prints
                         # "File error : Efinity project file does not exists" seven times
    "$EFINITY_HOME/bin/python3" "$SD/interface_tz170.py"
    # direct-clock SDC: constrain clk at the characterization target (CLKDIV=1)
    local period
    period=$(env -u PYTHONHOME -u PYTHONPATH /usr/bin/python3 -c "print(f'{1000.0/$TARGET_MHZ:.3f}')")
    printf 'create_clock -name clk -period %s [get_ports {clk}]\n' "$period" > "$SD/combined.sdc"
    : > "$SD/miner_defs.vh"
    printf '`define NRINGS %d\n`define CLKDIV 1\n' "$NRINGS" >> "$SD/miner_defs.vh"
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

do_clean() { cd "$SD"; rm -rf outflow work_syn work_pnr work_pt work_dbg; rm -f ${PROJECT}.xml ${PROJECT}.peri.xml *.log ring.v miner.v tz170_miner.v uart_tx.v epoch.vh params.vh prev256.vh miner_defs.vh combined.sdc; echo -e "${G}clean${N}"; }

case "${1:-build}" in
    build) do_build ;; clean) do_clean ;; *) echo "unknown: $1"; exit 1 ;;
esac
