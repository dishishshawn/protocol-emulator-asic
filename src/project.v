// SPDX-License-Identifier: Apache-2.0
// Replaced the Tiny Tapeout template example with the protocol engine wrapper.
`default_nettype none
module tt_um_dishishshawn_protocol_emulator (
    input wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input wire ena, clk, rst_n
);
    assign uio_out[7:5] = 0;
    assign uio_oe[7:5] = 0;
    protocol_engine engine (
        .clk(clk), .rst_n(rst_n), .ena(ena),
        .host_data(ui_in), .pins_in(uio_in),
        .pins_out(uio_out[4:0]), .pins_oe(uio_oe[4:0]), .status(uo_out)
    );
endmodule
