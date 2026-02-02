// link_monitor.sv
// Digital link monitoring and state machine
//
// Tracks CRC failures and maintains link up/down state based on
// consecutive failure/pass thresholds.

module link_monitor #(
    parameter int FAILS_TO_DOWN = 4,  // Consecutive fails to trigger link down
    parameter int PASSES_TO_UP = 8    // Consecutive passes to trigger link up
)(
    input  logic        clk,
    input  logic        rst_n,
    input  logic        valid,        // Frame present
    input  logic        crc_fail,     // CRC failure indication

    output logic        link_up,      // Link state (1=up, 0=down)
    output logic [31:0] total_frames,
    output logic [31:0] total_crc_fails,
    output logic [31:0] consec_fails,
    output logic [31:0] consec_passes
);

    // State and counters
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Reset: link starts up, all counters zero
            link_up          <= 1'b1;
            total_frames     <= 32'd0;
            total_crc_fails  <= 32'd0;
            consec_fails     <= 32'd0;
            consec_passes    <= 32'd0;
        end else if (valid) begin
            // Increment total frames
            total_frames <= total_frames + 32'd1;

            if (crc_fail) begin
                // CRC failure
                total_crc_fails <= total_crc_fails + 32'd1;
                consec_fails    <= consec_fails + 32'd1;
                consec_passes   <= 32'd0;

                // Check if we should transition to link down
                // Note: Compare against (consec_fails + 1) to use the post-increment
                // value in the comparison. This ensures that fails_to_down=4 means
                // "go down after 4 consecutive failures" as expected.
                if (link_up && ((consec_fails + 32'd1) >= FAILS_TO_DOWN)) begin
                    link_up <= 1'b0;
                end
            end else begin
                // CRC pass
                consec_passes <= consec_passes + 32'd1;
                consec_fails  <= 32'd0;

                // Check if we should transition to link up
                // Note: Compare against (consec_passes + 1) to use the post-increment
                // value in the comparison. This ensures that passes_to_up=8 means
                // "go up after 8 consecutive passes" as expected.
                if (!link_up && ((consec_passes + 32'd1) >= PASSES_TO_UP)) begin
                    link_up <= 1'b1;
                end
            end
        end
    end

endmodule
