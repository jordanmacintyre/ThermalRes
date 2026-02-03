// cosim_top.sv
// Top-level co-simulation wrapper for ThermalRes
//
// This module wraps link_monitor with:
// - Input ports for plant outputs (crc_fail_prob from Python)
// - LFSR-based Bernoulli event sampling
// - Output ports for link state and diagnostics
//
// The cocotb testbench drives the clock and provides crc_fail_prob
// from the Python plant model. This module samples the probability
// to generate discrete CRC events that feed the link_monitor.

module cosim_top #(
    parameter int FAILS_TO_DOWN = 4,      // Consecutive fails to trigger link down
    parameter int PASSES_TO_UP = 8,       // Consecutive passes to trigger link up
    parameter int LFSR_SEED = 32'hDEADBEEF // Seed for LFSR-based random sampling
)(
    input  logic        clk,
    input  logic        rst_n,
    input  logic        valid,            // Frame present this cycle
    input  logic [15:0] crc_fail_prob,    // Q0.16 probability from plant (0 = 0%, 65535 = ~100%)
    input  logic [31:0] lfsr_seed,        // Dynamic seed (optional, use LFSR_SEED if 0)

    // Link monitor outputs
    output logic        link_up,
    output logic        crc_fail,         // Sampled CRC fail event (for logging)
    output logic [31:0] total_frames,
    output logic [31:0] total_crc_fails,
    output logic [31:0] consec_fails,
    output logic [31:0] consec_passes,

    // Debug outputs
    output logic [31:0] lfsr_state        // Current LFSR state (for debugging)
);

    // ──────────────────────────────────────────────────────────────────
    // LFSR for pseudo-random number generation (Bernoulli sampling)
    //
    // 32-bit LFSR with polynomial x^32 + x^22 + x^2 + x + 1
    // This generates uniform random numbers for threshold comparison.
    // ──────────────────────────────────────────────────────────────────
    logic [31:0] lfsr_reg;
    logic        lfsr_feedback;

    // Galois LFSR feedback (taps at bits 31, 21, 1, 0)
    assign lfsr_feedback = lfsr_reg[31] ^ lfsr_reg[21] ^ lfsr_reg[1] ^ lfsr_reg[0];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Use dynamic seed if provided, otherwise use parameter
            lfsr_reg <= (lfsr_seed != 32'd0) ? lfsr_seed : LFSR_SEED;
        end else if (valid) begin
            // Shift LFSR on each valid frame
            lfsr_reg <= {lfsr_reg[30:0], lfsr_feedback};
        end
    end

    assign lfsr_state = lfsr_reg;

    // ──────────────────────────────────────────────────────────────────
    // Bernoulli event sampling
    //
    // Compare LFSR output (uniform random) against crc_fail_prob threshold.
    // If lfsr[15:0] < crc_fail_prob, then CRC failure occurs.
    //
    // This implements P(crc_fail) = crc_fail_prob / 65536
    // ──────────────────────────────────────────────────────────────────
    logic crc_fail_sampled;

    always_comb begin
        // Threshold comparison: fail if random < probability
        // Using upper 16 bits of LFSR for better randomness distribution
        crc_fail_sampled = (lfsr_reg[31:16] < crc_fail_prob);
    end

    // Register the sampled event for output
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            crc_fail <= 1'b0;
        end else if (valid) begin
            crc_fail <= crc_fail_sampled;
        end
    end

    // ──────────────────────────────────────────────────────────────────
    // Link Monitor Instance
    // ──────────────────────────────────────────────────────────────────
    link_monitor #(
        .FAILS_TO_DOWN(FAILS_TO_DOWN),
        .PASSES_TO_UP(PASSES_TO_UP)
    ) u_link_monitor (
        .clk            (clk),
        .rst_n          (rst_n),
        .valid          (valid),
        .crc_fail       (crc_fail_sampled),  // Feed sampled event to link monitor

        .link_up        (link_up),
        .total_frames   (total_frames),
        .total_crc_fails(total_crc_fails),
        .consec_fails   (consec_fails),
        .consec_passes  (consec_passes)
    );

endmodule
