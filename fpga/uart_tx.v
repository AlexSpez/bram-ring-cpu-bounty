// uart_tx.v — minimal 8N1 UART transmitter (no parity, 1 stop bit).
// Assert `send` with `data` valid for one clock; `busy` stays high until the
// byte is shifted out at BAUD. Self-contained (no vendor IP).
module uart_tx #(
    parameter integer CLK_HZ = 25_000_000,
    parameter integer BAUD   = 115200
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] data,
    input  wire       send,
    output reg        tx,
    output reg        busy
);
    localparam integer DIV = CLK_HZ / BAUD;
    reg [15:0] cnt;
    reg [3:0]  bit_i;
    reg [9:0]  shreg;      // {stop=1, data[7:0], start=0}
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx<=1'b1; busy<=1'b0; cnt<=0; bit_i<=0; shreg<=10'h3FF;
        end else if (!busy) begin
            tx<=1'b1;
            if (send) begin
                shreg <= {1'b1, data, 1'b0};   // stop, data, start
                busy<=1'b1; cnt<=0; bit_i<=0;
            end
        end else begin
            if (cnt == DIV-1) begin
                cnt<=0; tx<=shreg[0]; shreg<={1'b1, shreg[9:1]};
                if (bit_i == 9) busy<=1'b0; else bit_i<=bit_i+1'b1;
            end else cnt<=cnt+1'b1;
        end
    end
endmodule
