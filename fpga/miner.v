// miner.v — wraps the ring core (ring.v) into a nonce-searching miner.
//
// Pipelined background seeding, two-cycle XOR fold, pool-style hash counter,
// with two fabric diets that together cut the wrapper from ~3 to ~1 B*W-bit
// register vs the straightforward version:
//   * no r_state_in: the ring latches state_in in the single IDLE->start
//     cycle, so the seed shadow register (r_state_next) feeds the ring
//     directly -- the seeder only begins overwriting the shadow two cycles
//     after `start`, one cycle after the ring has latched it.
//   * PREV chunks come from a 256-bit rotating register: spec's
//     PREVCHUNK[b] is PREV rotated right by b*W, low W bits. Self-restoring
//     per seeding pass because (B*W) % 256 == 0 (asserted by generate.py).
//
// Instantiates module `ring` -- the board flows rename
// module `ring` from ring.v (already so named in this repo).
`include "params.vh"                       // `RING_B / `RING_W from spec.py
module miner #(
    parameter [63:0] EPOCH_CONST = 64'h0,
    parameter [63:0] NONCE0  = 64'd0,      // this ring's first nonce
    parameter [63:0] NSTRIDE = 64'd1,      // nonce step (= #rings, so rings interleave)
    parameter integer B = `RING_B,
    parameter integer W = `RING_W
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] target,        // solution if fold(state) <= target
    output reg         found,
    output reg  [63:0] sol_nonce,
    output reg  [31:0] sol_fold,
    output reg  [63:0] hash_count
);
    localparam integer NB = B*W;
    `include "prev256.vh"                  // raw 256-bit PREV constant

    // ---- ring core (state_in = the seed shadow, latched at IDLE->start) ----
    reg           r_start;
    wire          r_done;
    reg  [NB-1:0] r_state_next;            // shadow seeds, filled while the ring runs
    wire [NB-1:0] r_state_out;
    ring u_ring(.clk(clk), .rst_n(rst_n), .start(r_start),
                .state_in(r_state_next), .done(r_done), .state_out(r_state_out));

    function [63:0] xshift(input [63:0] s0);
        reg [63:0] s;
        begin s = s0; s = s ^ (s<<13); s = s ^ (s>>7); s = s ^ (s<<17); xshift = s; end
    endfunction

    // ---- fold the ring state to 32 bits by XOR (two-cycle pipeline) ----
    localparam integer NW = (NB+31)/32, HW = NW/2;
    integer wi;
    reg [31:0] fold_lo, fold_hi;
    always @* begin
        fold_lo = 32'h0;
        for (wi = 0;  wi < HW; wi = wi + 1) fold_lo = fold_lo ^ r_state_out[wi*32 +: 32];
    end
    always @* begin
        fold_hi = 32'h0;
        for (wi = HW; wi < NW; wi = wi + 1) fold_hi = fold_hi ^ r_state_out[wi*32 +: 32];
    end

    // ---- FSM: pipelined seeding into the single shadow register ----
    // While the ring runs nonce N (~2562 cycles), the seeder rebuilds the
    // shadow with N+1's seeds (B cycles, B < ring cycles so it hides). On
    // ring-done: fold/check N, pulse start (ring latches the shadow next
    // cycle), and only then start_seed lets the seeder touch the shadow again.
    localparam S_BOOT=0, S_BOOTW=1, S_KICK=2, S_RUN=3, S_FOLD=4, S_FOLD2=6, S_SWAP=5;
    reg [2:0]  st;
    reg [31:0] fold_r, fold_a;
    reg [63:0] seed_nonce, run_nonce, sreg;
    reg        seeding, seed_ready, start_seed;
    reg [15:0] seed_i;
    reg [255:0] pv_sh;                     // rotating PREV; chunk b = pv_sh[W-1:0]
    wire [63:0] sreg_next = xshift(sreg);
    wire [W-1:0] new_lane = sreg_next[W-1:0] ^ pv_sh[W-1:0];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st<=S_BOOT; seed_nonce<=NONCE0; run_nonce<=NONCE0; found<=1'b0; hash_count<=64'd0;
            r_start<=1'b0; r_state_next<=0; sreg<=0; pv_sh<=PREV256;
            seeding<=1'b0; seed_ready<=1'b0; start_seed<=1'b0; seed_i<=16'd0;
        end else begin
            start_seed <= 1'b0;                            // default: one-cycle pulse
            // ---- background seeder: seed_nonce -> r_state_next over B cycles ----
            if (start_seed) begin
                sreg <= seed_nonce ^ EPOCH_CONST;
                seed_i <= 16'd0; seeding <= 1'b1; seed_ready <= 1'b0;
            end else if (seeding) begin
                sreg         <= sreg_next;                  // one lane/cycle: no wide demux
                pv_sh        <= {pv_sh[W-1:0], pv_sh[255:W]};       // rotate right by W
                r_state_next <= {new_lane, r_state_next[NB-1:W]};   // lane i lands at position i
                if (seed_i == B-1) begin seeding <= 1'b0; seed_ready <= 1'b1; end
                seed_i <= seed_i + 1'b1;
            end
            // ---- ring controller ----
            case (st)
                S_BOOT:  begin start_seed <= 1'b1; st <= S_BOOTW; end  // seed nonce 0 into shadow
                S_BOOTW: if (seed_ready) begin                         // first seeds ready
                    run_nonce <= seed_nonce;
                    seed_nonce <= seed_nonce + NSTRIDE; start_seed <= 1'b1;   // seed next
                    seed_ready <= 1'b0; r_start <= 1'b1; st <= S_KICK;
                end
                S_KICK:  begin r_start <= 1'b0; st <= S_RUN; end // ring latches the shadow here
                S_RUN:   if (r_done) st <= S_FOLD;              // state_out stable at FIN
                S_FOLD:  begin fold_a <= fold_lo; st <= S_FOLD2; end          // half the tree
                S_FOLD2: begin fold_r <= fold_a ^ fold_hi; st <= S_SWAP; end  // combine
                S_SWAP:  begin
                    hash_count <= hash_count + 1'b1;
                    // sol_fold tracks every fold until a hit, then holds the
                    // BEST (lowest-fold) solution seen and keeps improving --
                    // it never freezes, so a race at any difficulty above
                    // `target`'s zeros can still be won by a later, deeper
                    // solution (a frozen first-hit latch rigged `make race`
                    // against the board; found 2026-08-05, first-contact review).
                    // Keeping all 32 bits live stops efx_map const-folding
                    // sol_fold[31:16] (target's upper bits are 0), which put
                    // a variable part-select over a half-deleted vector in
                    // the UART formatter and read back a stuck bit on silicon.
                    if (!found) begin
                        sol_fold <= fold_r;
                        if (fold_r <= target) begin
                            found <= 1'b1; sol_nonce <= run_nonce;
                        end
                    end else if (fold_r < sol_fold) begin
                        sol_fold <= fold_r; sol_nonce <= run_nonce;
                    end
                    if (seed_ready) begin                       // shadow ready -> keep the pipe full
                        run_nonce <= seed_nonce;
                        seed_nonce <= seed_nonce + NSTRIDE; start_seed <= 1'b1;
                        seed_ready <= 1'b0; r_start <= 1'b1; st <= S_KICK;
                    end
                end
            endcase
        end
    end
endmodule
