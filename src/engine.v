// SPDX-License-Identifier: Apache-2.0
// Prototype instruction engine. Program RAM is deliberately not reset.
`default_nettype none
module protocol_engine (
    input wire clk, rst_n, ena,
    input wire [7:0] host_data,
    input wire [7:0] pins_in,
    output wire [4:0] pins_out, pins_oe,
    output wire [7:0] status
);
    reg [7:0] input_meta, input_sync;
    reg load_prev, run_prev;
    wire load = input_sync[7];
    wire run = input_sync[6];
    wire rewind_program = input_sync[5];
    reg [31:0] program_mem [0:63];
    reg [23:0] assembly_bytes;
    reg [1:0] byte_index;
    reg [6:0] length;
    reg loader_error;
    reg [6:0] pc;
    reg [17:0] delay_left;
    reg [17:0] wait_elapsed;
    reg [7:0] tx_shift, rx_shift, loop_count;
    reg last_tx_bit;
    reg [4:0] out_value, out_enable, sampled;
    reg running, halted, fault;
    wire [31:0] instruction = program_mem[pc[5:0]];
    assign pins_out = out_value;
    assign pins_oe = (ena && rst_n) ? out_enable : 5'b0;
    // REWIND doubles as a result-page select only after execution has halted.
    assign status = (run && halted && rewind_program) ? rx_shift :
                    {fault, running, halted, sampled};

    task fail_closed;
        begin
            running <= 0;
            halted <= 1;
            fault <= 1;
            out_enable <= 0;
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            input_meta <= 0;
            input_sync <= 0;
            load_prev <= 0;
            run_prev <= 0;
            assembly_bytes <= 0;
            byte_index <= 0;
            length <= 0;
            loader_error <= 0;
            pc <= 0;
            delay_left <= 0;
            wait_elapsed <= 0;
            tx_shift <= 0;
            rx_shift <= 0;
            loop_count <= 0;
            last_tx_bit <= 0;
            out_value <= 0;
            out_enable <= 0;
            sampled <= 0;
            running <= 0;
            halted <= 0;
            fault <= 0;
        end else begin
            input_meta <= pins_in;
            input_sync <= input_meta;
            load_prev <= load;
            run_prev <= run;

            if (ena && !run) begin
                if (rewind_program) begin
                    length <= 0;
                    byte_index <= 0;
                    loader_error <= 0;
                end else if (load && !load_prev) begin
                    if (length == 64) begin
                        loader_error <= 1;
                    end else begin
                        case (byte_index)
                            0: assembly_bytes[7:0] <= host_data;
                            1: assembly_bytes[15:8] <= host_data;
                            2: assembly_bytes[23:16] <= host_data;
                            3: begin
                                program_mem[length[5:0]] <= {host_data, assembly_bytes};
                                length <= length + 1'b1;
                            end
                        endcase
                        byte_index <= byte_index + 1'b1;
                    end
                end
            end

            if (!ena || !run) begin
                running <= 0;
                halted <= 0;
                fault <= 0;
                pc <= 0;
                delay_left <= 0;
                out_enable <= 0;
            end else if (!run_prev) begin
                pc <= 0;
                delay_left <= 0;
                wait_elapsed <= 0;
                tx_shift <= 0;
                rx_shift <= 0;
                loop_count <= 0;
                last_tx_bit <= 0;
                out_enable <= 0;
                sampled <= 0;
                if (length == 0 || byte_index != 0 || loader_error) begin
                    running <= 0;
                    halted <= 1;
                    fault <= 1;
                end else begin
                    running <= 1;
                    halted <= 0;
                    fault <= 0;
                end
            end else if (running) begin
                if (delay_left != 0) begin
                    delay_left <= delay_left - 1'b1;
                end else if (pc >= length) begin
                    running <= 0;
                    halted <= 1;
                    fault <= 1;
                    out_enable <= 0;
                end else begin
                    case (instruction[31:28])
                        4'h0: begin // DRIVE: duration-minus-one, OE mask, value
                            out_value <= instruction[4:0];
                            out_enable <= instruction[9:5];
                            delay_left <= instruction[27:10];
                            pc <= pc + 1'b1;
                        end
                        4'h1: begin // WAIT: pin index [2:0], expected level [3]
                            if (instruction[2:0] > 4) begin
                                running <= 0;
                                halted <= 1;
                                fault <= 1;
                                out_enable <= 0;
                            end else if (input_sync[instruction[2:0]] == instruction[3]) begin
                                wait_elapsed <= 0;
                                pc <= pc + 1'b1;
                            end else if (instruction[27:10] != 0) begin
                                if (wait_elapsed == instruction[27:10] - 1'b1)
                                    fail_closed();
                                else wait_elapsed <= wait_elapsed + 1'b1;
                            end
                        end
                        4'h2: pc <= {1'b0, instruction[5:0]};
                        4'h3: begin
                            sampled <= input_sync[4:0];
                            pc <= pc + 1'b1;
                        end
                        4'h4: begin // LOAD: byte, bit count; begin fresh receive byte
                            tx_shift <= instruction[7:0];
                            loop_count <= instruction[15:8];
                            rx_shift <= 0;
                            pc <= pc + 1'b1;
                        end
                        4'h5: begin // OUT: lane, LSB-first, open-drain
                            if (instruction[2:0] > 4) fail_closed();
                            else begin
                                last_tx_bit <= instruction[3] ? tx_shift[0] : tx_shift[7];
                                out_value[instruction[2:0]] <= instruction[4] ? 1'b0 :
                                    (instruction[3] ? tx_shift[0] : tx_shift[7]);
                                out_enable[instruction[2:0]] <= !instruction[4] ||
                                    !(instruction[3] ? tx_shift[0] : tx_shift[7]);
                                tx_shift <= instruction[3] ? {1'b0, tx_shift[7:1]} :
                                    {tx_shift[6:0], 1'b0};
                                pc <= pc + 1'b1;
                            end
                        end
                        4'h6: begin // IN: synchronized lane, LSB-first
                            if (instruction[2:0] > 4) fail_closed();
                            else begin
                                rx_shift <= instruction[3] ?
                                    {input_sync[instruction[2:0]], rx_shift[7:1]} :
                                    {rx_shift[6:0], input_sync[instruction[2:0]]};
                                pc <= pc + 1'b1;
                            end
                        end
                        4'h7: begin // DJNZ: zero count is an error, not 256 iterations
                            if (loop_count == 0) fail_closed();
                            else begin
                                loop_count <= loop_count - 1'b1;
                                pc <= (loop_count == 1) ? pc + 1'b1 :
                                    {1'b0, instruction[5:0]};
                            end
                        end
                        4'h8: begin // BRANCH: lane, level, address [9:4]
                            if (instruction[2:0] > 4) fail_closed();
                            else pc <= (input_sync[instruction[2:0]] == instruction[3]) ?
                                {1'b0, instruction[9:4]} : pc + 1'b1;
                        end
                        4'h9: begin // CHECK_TX: compare lane against last OUT bit
                            if (instruction[2:0] > 4 ||
                                input_sync[instruction[2:0]] != last_tx_bit)
                                fail_closed();
                            else pc <= pc + 1'b1;
                        end
                        4'ha: fail_closed(); // software TRAP, e.g. NACK path
                        4'hb: begin // PATCH: change only masked lanes, then delay
                            out_value <= (out_value & ~instruction[14:10]) |
                                         (instruction[4:0] & instruction[14:10]);
                            out_enable <= (out_enable & ~instruction[14:10]) |
                                          (instruction[9:5] & instruction[14:10]);
                            delay_left <= {5'b0, instruction[27:15]};
                            pc <= pc + 1'b1;
                        end
                        4'hf: begin
                            running <= 0;
                            halted <= 1;
                            out_enable <= 0;
                        end
                        default: begin
                            running <= 0;
                            halted <= 1;
                            fault <= 1;
                            out_enable <= 0;
                        end
                    endcase
                end
            end
        end
    end
endmodule
