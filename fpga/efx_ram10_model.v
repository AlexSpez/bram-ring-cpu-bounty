// efx_ram10_model.v — SIMULATION-ONLY behavioral model of the Efinity Titanium
// EFX_RAM10 block-RAM primitive, covering the subset of ports/params the ring uses
// (simple dual port, WRITE_MODE="READ_FIRST", OUTPUT_REG=0, reset disabled).
//
// Do NOT add this file to an Efinity project — efx_map recognizes EFX_RAM10 natively
// and would conflict. It exists only so `iverilog` can run tb_vectors.v / tb_vectors.v
// without the vendor sim model. The real hardware is bit-exact with spec (verified
// on a Ti375); this model reproduces the same read-first, 1-cycle-latency behavior.
`timescale 1ns/1ps
module EFX_RAM10 #(
    parameter READ_WIDTH  = 16,
    parameter WRITE_WIDTH = 16,
    parameter OUTPUT_REG  = 1'b0,
    parameter WRITE_MODE  = "READ_FIRST",
    parameter [1:0] WE_POLARITY      = 2'b11,
    parameter WCLKE_POLARITY  = 1'b1,
    parameter WADDREN_POLARITY = 1'b1,
    parameter RADDREN_POLARITY = 1'b1,
    parameter RE_POLARITY      = 1'b1,
    parameter RESET_RAM    = "NONE",
    parameter RESET_OUTREG = "NONE"
)(
    input  wire        WCLK, RCLK, WCLKE, WADDREN, RADDREN, RST, RE,
    input  wire [1:0]  WE,
    input  wire [WRITE_WIDTH-1:0] WDATA,
    input  wire [8:0]  WADDR,        // 512-deep for 20-bit width
    input  wire [8:0]  RADDR,
    output reg  [READ_WIDTH-1:0] RDATA
);
    reg [READ_WIDTH-1:0] mem [0:511];
    // write and read in separate blocks; non-blocking => a same-address read returns
    // the OLD value (READ_FIRST), which is all the ring relies on.
    always @(posedge WCLK)
        if (WE[0] & WCLKE) mem[WADDR] <= WDATA;
    always @(posedge RCLK)
        if (RE) RDATA <= mem[RADDR];
endmodule
