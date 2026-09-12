// PARAGATO CV-X-IF coprocessor: 4-Lane INT8 SIMD Dot-Product & Accumulate.
//
// Implements the pg.sdot4 custom instruction:
//     pg.sdot4 rd, rs1, rs2, rs3
//         rd <- rs3 + (rs1[7:0] * rs2[7:0])
//                   + (rs1[15:8] * rs2[15:8])
//                   + (rs1[23:16] * rs2[23:16])
//                   + (rs1[31:24] * rs2[31:24])
//
// Encoded as R4-type in RISC-V custom-2 space (0x5B):
//     rs3 = instr[31:27], funct2 = 01, funct3 = 000, opcode = 1011011 (0x5b)

module pg_xif_tinyml
  
#(
  parameter int X_NUM_RS    = 3,
  parameter int X_ID_WIDTH  = 4,
  parameter int X_RFR_WIDTH = 32,
  parameter int X_RFW_WIDTH = 32
)
(
  input  logic clk_i,
  input  logic rst_ni,
  if_xif.coproc_compressed xif_compressed_if,
  if_xif.coproc_issue      xif_issue_if,
  if_xif.coproc_commit     xif_commit_if,
  if_xif.coproc_mem        xif_mem_if,
  if_xif.coproc_mem_result xif_mem_result_if,
  if_xif.coproc_result     xif_result_if
);

  // ---------------------------------------------------------------- decode --
  localparam logic [6:0] OPCODE_CUSTOM2 = 7'b1011011; // custom-2
  localparam logic [2:0] FUNCT3_SDOT4   = 3'b000;
  localparam logic [1:0] FUNCT2_SDOT4   = 2'b01;

  logic [31:0] instr;
  logic        is_sdot4;

  // Result-holding registers
  logic                   res_pending;
  logic [31:0]            res_data;
  logic [4:0]             res_rd;
  logic [X_ID_WIDTH-1:0]  res_id;

  assign instr    = xif_issue_if.issue_req.instr;
  assign is_sdot4 = xif_issue_if.issue_valid && !res_pending
                    && (instr[6:0]   == OPCODE_CUSTOM2)
                    && (instr[14:12] == FUNCT3_SDOT4)
                    && (instr[26:25] == FUNCT2_SDOT4);

  // ----------------------------------------------------------------- issue --
  assign xif_issue_if.issue_ready              = !res_pending;
  assign xif_issue_if.issue_resp.accept        = is_sdot4;
  assign xif_issue_if.issue_resp.writeback     = is_sdot4;
  assign xif_issue_if.issue_resp.dualwrite     = 1'b0;
  assign xif_issue_if.issue_resp.dualread      = 3'b000;
  assign xif_issue_if.issue_resp.loadstore     = 1'b0;
  assign xif_issue_if.issue_resp.ecswrite      = 1'b0;
  assign xif_issue_if.issue_resp.exc           = 1'b0;

  // --------------------------------------------------------------- compute --
  logic signed [7:0] a0, a1, a2, a3;
  logic signed [7:0] b0, b1, b2, b3;

  assign a0 = xif_issue_if.issue_req.rs[0][7:0];
  assign a1 = xif_issue_if.issue_req.rs[0][15:8];
  assign a2 = xif_issue_if.issue_req.rs[0][23:16];
  assign a3 = xif_issue_if.issue_req.rs[0][31:24];

  assign b0 = xif_issue_if.issue_req.rs[1][7:0];
  assign b1 = xif_issue_if.issue_req.rs[1][15:8];
  assign b2 = xif_issue_if.issue_req.rs[1][23:16];
  assign b3 = xif_issue_if.issue_req.rs[1][31:24];

  // 4 parallel 8x8 signed multipliers
  logic signed [15:0] prod0, prod1, prod2, prod3;
  assign prod0 = a0 * b0;
  assign prod1 = a1 * b1;
  assign prod2 = a2 * b2;
  assign prod3 = a3 * b3;

  // Adder tree + 32-bit accumulator
  logic signed [31:0] sum_prods;
  logic signed [31:0] total_sum;

  assign sum_prods  = {{16{prod0[15]}}, prod0} +
                      {{16{prod1[15]}}, prod1} +
                      {{16{prod2[15]}}, prod2} +
                      {{16{prod3[15]}}, prod3};

  assign total_sum  = signed'(xif_issue_if.issue_req.rs[2]) + sum_prods;

  // ---------------------------------------------------------------- result --
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      res_pending <= 1'b0;
      res_data    <= '0;
      res_rd      <= '0;
      res_id      <= '0;
    end else if (is_sdot4) begin
      res_pending <= 1'b1;
      res_data    <= logic'(total_sum);
      res_rd      <= instr[11:7];
      res_id      <= xif_issue_if.issue_req.id;
    end else if (res_pending && xif_result_if.result_ready) begin
      res_pending <= 1'b0;
    end else if (res_pending && xif_commit_if.commit_valid
                 && xif_commit_if.commit.commit_kill
                 && (xif_commit_if.commit.id == res_id)) begin
      res_pending <= 1'b0;
    end
  end

  assign xif_result_if.result_valid   = res_pending;
  assign xif_result_if.result.id      = res_id;
  assign xif_result_if.result.data    = res_data;
  assign xif_result_if.result.rd      = res_rd;
  assign xif_result_if.result.we      = 1'b1;
  assign xif_result_if.result.ecsdata = '0;
  assign xif_result_if.result.ecswe   = '0;
  assign xif_result_if.result.exc     = 1'b0;
  assign xif_result_if.result.exccode = '0;

  // ------------------------------------------------ unused sub-interfaces --
  assign xif_compressed_if.compressed_ready       = 1'b1;
  assign xif_compressed_if.compressed_resp.instr  = '0;
  assign xif_compressed_if.compressed_resp.accept = 1'b0;

  assign xif_mem_if.mem_valid                     = 1'b0;
  assign xif_mem_if.mem_req                       = '0;

endmodule
