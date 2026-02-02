// top.sv
// Top-level wrapper for link_monitor
//
// Exposes same interface as link_monitor for cocotb testing

module top #(
    parameter int FAILS_TO_DOWN = 4,
    parameter int PASSES_TO_UP = 8
)(
    input  logic        clk,
    input  logic        rst_n,
    input  logic        valid,
    input  logic        crc_fail,

    output logic        link_up,
    output logic [31:0] total_frames,
    output logic [31:0] total_crc_fails,
    output logic [31:0] consec_fails,
    output logic [31:0] consec_passes
);

    link_monitor #(
        .FAILS_TO_DOWN(FAILS_TO_DOWN),
        .PASSES_TO_UP(PASSES_TO_UP)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .valid(valid),
        .crc_fail(crc_fail),
        .link_up(link_up),
        .total_frames(total_frames),
        .total_crc_fails(total_crc_fails),
        .consec_fails(consec_fails),
        .consec_passes(consec_passes)
    );

endmodule
