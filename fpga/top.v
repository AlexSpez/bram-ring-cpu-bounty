// top.v — board-agnostic miner top: NRINGS parallel BRAM-ring miners + UART.
//
// NRINGS independent miner cores (miner.v -> ring.v) search interleaved nonce
// streams (ring i does nonces i, i+NRINGS, ...). Their hash_counts sum, so the
// host reads NRINGS x the single-ring rate. Streams an ASCII status line over
// UART (F4, FTDI ch C) every ~0.5 s:
//     <hash_count:16hex> <sol_nonce:16hex> <sol_fold:8hex> <found>\n
//
// CLKDIV>1 gates the fabric clock to base/CLKDIV via EFX_GBUFCE (global clock
// buffer w/ enable) -- the clock net stops toggling CLKDIV-1 of every CLKDIV
// cycles, so dynamic power drops ~CLKDIV x. Lets many rings run inside a small
// (USB) power budget; scale the measured rate up by CLKDIV to get full-clock.
`include "epoch.vh"
`include "miner_defs.vh"   // build script: `define PLL / PLL_CLK_HZ / NRINGS / CLKDIV
`ifndef NRINGS
 `define NRINGS 1
`endif
`ifndef CLKDIV
 `define CLKDIV 1
`endif

`ifdef PLL
module miner_top (
    input  wire clk_ref,     // K6 33.3 MHz osc -> PLL refclk (unused in RTL)
    input  wire clk0_unused, // PLL CLKOUT0 feedback (unused in RTL)
    input  wire clk,         // PLL CLKOUT1 -> raw fabric clock
    input  wire pll_locked,  // PLL lock status
    output wire uart_tx, output reg led_g, output reg led_b,
    output wire uart_rts_n   // M8 = pll_locked
);
    localparam integer BASE_HZ = `PLL_CLK_HZ;
    assign uart_rts_n = pll_locked;
`else
module miner_top (
    input  wire clk,         // K6 33.3 MHz osc -> raw fabric clock
    output wire uart_tx, output reg led_g, output reg led_b
);
    localparam integer BASE_HZ = 33_333_333;
`endif
    localparam integer NRINGS = `NRINGS;
    localparam integer CLKDIV = `CLKDIV;
    localparam integer CLK_HZ = BASE_HZ / CLKDIV;   // effective clock (drives UART baud)
    localparam [31:0]  TARGET = 32'h0000_FFFF;      // 16 leading-zero bits

    // ---- optional clock divide: effective clock = clk / CLKDIV (CLKDIV even) ----
    // Divide with a toggle flop -- clk drives ONLY these flops (clock ports), NOT
    // a clock buffer, so no VDB-9015 ("clock net drives ports AND a buffer"). Then
    // EFX_GBUFCE buffers the DIVIDED clock onto the global network. Both clock-net
    // and logic toggle at 1/CLKDIV -> ~CLKDIV x less dynamic power (USB budget).
    wire clk_g;
    generate if (CLKDIV <= 1) begin : g_direct
        assign clk_g = clk;                          // already on a global net
    end else begin : g_gate
        localparam integer HALF = CLKDIV/2;
        reg [15:0] dc = 16'd0; reg cks = 1'b0;
        always @(posedge clk) begin
            if (dc == HALF[15:0]-16'd1) begin dc <= 16'd0; cks <= ~cks; end
            else                       begin dc <= dc + 16'd1; end
        end
        EFX_GBUFCE #(.CE_POLARITY(1'b1)) u_gbuf (.CE(1'b1), .I(cks), .O(clk_g));
    end endgenerate

    // ---- power-on reset (on the effective clock) ----
    reg [7:0] por = 8'h00;
    wire rst_n = por[7];
    always @(posedge clk_g) if (!por[7]) por <= por + 1'b1;

    // ---- NRINGS parallel miners on interleaved nonce streams ----
    // Outputs are PACKED vectors (not unpacked wire arrays): variable-indexed
    // unpacked-array reads in a combinational sum synthesize wrong on efx_map
    // (silicon read 1x + a garbage solution) though iverilog handled them.
    // Packed slices hc_flat[k*64 +: 64] are a plain mux -> reliable.
    wire [NRINGS*64-1:0] hc_flat, sn_flat;
    wire [NRINGS*32-1:0] sf_flat;
    wire [NRINGS-1:0]    found_i;
    genvar gi;
    generate for (gi = 0; gi < NRINGS; gi = gi + 1) begin : g_ring
        miner #(.EPOCH_CONST(`EPOCH_CONST), .NONCE0(gi), .NSTRIDE(NRINGS)) u_miner (
            .clk(clk_g), .rst_n(rst_n), .target(TARGET), .found(found_i[gi]),
            .sol_nonce(sn_flat[gi*64 +: 64]), .sol_fold(sf_flat[gi*32 +: 32]),
            .hash_count(hc_flat[gi*64 +: 64]));
    end endgenerate

    // aggregate: sum the counts, take the first ring reporting a solution
    integer k;
    reg [63:0] hc_sum, sn_any; reg [31:0] sf_any; reg found_any;
    always @* begin
        hc_sum = 64'd0;
        for (k = 0; k < NRINGS; k = k + 1) hc_sum = hc_sum + hc_flat[k*64 +: 64];
        found_any = |found_i; sn_any = 64'd0; sf_any = 32'd0;
        for (k = NRINGS-1; k >= 0; k = k - 1)
            if (found_i[k]) begin sn_any = sn_flat[k*64 +: 64]; sf_any = sf_flat[k*32 +: 32]; end
    end

    // ---- UART transmitter ----
    reg  [7:0] tx_data; reg tx_send; wire tx_busy;
    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(115200)) u_uart (
        .clk(clk_g), .rst_n(rst_n), .data(tx_data), .send(tx_send),
        .tx(uart_tx), .busy(tx_busy));

    // ---- ASCII frame emitter (45 bytes) ----
    function [7:0] hexc(input [3:0] n);
        hexc = (n < 4'd10) ? (8'h30 + {4'd0,n}) : (8'h61 + {4'd0,n} - 8'd10);
    endfunction
    reg [63:0] hc, nn; reg [31:0] fo; reg fbit;
    reg [5:0]  idx; reg [23:0] tick;
    localparam E_IDLE=0, E_SEND=1, E_WAIT=2; reg [1:0] est;
    reg [7:0] bb;
    always @* begin
        if      (idx < 6'd16)  bb = hexc(hc[(6'd15-idx)*4 +: 4]);
        else if (idx == 6'd16) bb = " ";
        else if (idx < 6'd33)  bb = hexc(nn[(6'd32-idx)*4 +: 4]);
        else if (idx == 6'd33) bb = " ";
        else if (idx < 6'd42)  bb = hexc(fo[(6'd41-idx)*4 +: 4]);
        else if (idx == 6'd42) bb = " ";
        else if (idx == 6'd43) bb = fbit ? "1" : "0";
        else                   bb = 8'h0a;
    end
    always @(posedge clk_g or negedge rst_n) begin
        if (!rst_n) begin
            est <= E_IDLE; idx <= 0; tick <= 0; tx_send <= 0; led_g <= 0; led_b <= 0;
        end else begin
            tick   <= tick + 1'b1;
            led_b  <= found_any;
            led_g  <= hc_sum[22];
            tx_send <= 1'b0;
            case (est)
                E_IDLE: if (tick == 24'h0) begin
                            hc <= hc_sum; nn <= sn_any; fo <= sf_any; fbit <= found_any;
                            idx <= 0; est <= E_SEND;
                        end
                E_SEND: if (!tx_busy) begin tx_data <= bb; tx_send <= 1'b1; est <= E_WAIT; end
                E_WAIT: if (!tx_busy) begin
                            if (idx == 6'd44) est <= E_IDLE;
                            else begin idx <= idx + 1'b1; est <= E_SEND; end
                        end
            endcase
        end
    end
endmodule
