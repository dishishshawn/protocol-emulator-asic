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
    reg stream_enabled;
    reg [7:0] byte_count;
    reg [7:0] tx_fifo [0:7];
    reg [7:0] rx_fifo [0:7];
    reg [31:0] capture_fifo [0:7];
    reg [2:0] tx_rd, tx_wr, rx_rd, rx_wr, capture_rd, capture_wr;
    reg [3:0] tx_used, rx_used, capture_used;
    reg [3:0] read_page;
    reg [5:0] host_errors;
    reg [23:0] timestamp;
    reg [4:0] capture_mask, capture_prev;
    reg [7:0] page_data;
    wire [31:0] instruction = program_mem[pc[5:0]];
    wire issue = ena && run && run_prev && running && delay_left == 0 && pc < length;
    wire host_strobe = stream_enabled && load && !load_prev;
    wire command = host_strobe && rewind_program;
    wire tx_push = host_strobe && !rewind_program && tx_used < 8;
    wire tx_pop = issue && stream_enabled && instruction[31:24] == 8'hc2 && tx_used != 0;
    wire rx_push = issue && stream_enabled && instruction[31:24] == 8'hc3 && rx_used < 8;
    wire rx_pop = command && host_data == 8'h80 && rx_used != 0;
    wire capture_event = running && |((input_sync[4:0] ^ capture_prev) & capture_mask);
    wire capture_push = capture_event && capture_used < 8;
    wire capture_pop = command && host_data == 8'h81 && capture_used != 0;
    wire [31:0] capture_head = capture_used != 0 ? capture_fifo[capture_rd] : 32'b0;
    assign pins_out = out_value;
    assign pins_oe = (ena && rst_n) ? out_enable : 5'b0;
    // Legacy programs keep the original halted RX page; streaming opts in to pages.
    assign status = (run && rewind_program && (halted || stream_enabled)) ? page_data :
                    {fault, running, halted, sampled};

    always @* begin
        case (read_page)
            0: page_data = rx_shift;
            1: page_data = {fault, running, halted, stream_enabled, |host_errors,
                            tx_used < 8, rx_used != 0, capture_used != 0};
            2: page_data = {4'b0, tx_used};
            3: page_data = {4'b0, rx_used};
            4: page_data = rx_used != 0 ? rx_fifo[rx_rd] : 8'b0;
            5: page_data = {4'b0, capture_used};
            6: page_data = capture_head[7:0];
            7: page_data = capture_head[15:8];
            8: page_data = capture_head[23:16];
            9: page_data = capture_head[31:24];
            10: page_data = {2'b0, host_errors};
            default: page_data = 0;
        endcase
    end

    // All queues share the engine clock. Full/empty decisions use pre-edge counts:
    // a full queue retries on the next clock even if a pop happens this clock.
    always @(posedge clk) begin
        if (!rst_n || !ena || !run || !run_prev) begin
            tx_rd <= 0; tx_wr <= 0; tx_used <= 0;
            rx_rd <= 0; rx_wr <= 0; rx_used <= 0;
            capture_rd <= 0; capture_wr <= 0; capture_used <= 0;
            read_page <= 0;
            host_errors <= 0;
            timestamp <= 0;
            capture_prev <= input_sync[4:0];
        end else begin
            timestamp <= timestamp + 1'b1;
            capture_prev <= input_sync[4:0];
            if (command && host_data == 8'h82) host_errors <= 0;
            if (command) begin
                if (host_data <= 10) read_page <= host_data[3:0];
                else if (host_data != 8'h80 && host_data != 8'h81 && host_data != 8'h82)
                    host_errors[4] <= 1;
            end
            if (host_strobe && !rewind_program && tx_used == 8) host_errors[0] <= 1;
            if (command && host_data == 8'h80 && rx_used == 0) host_errors[1] <= 1;
            if (command && host_data == 8'h81 && capture_used == 0) host_errors[2] <= 1;
            if (capture_event && capture_used == 8) host_errors[3] <= 1;
            if (running && timestamp == 24'hffffff) host_errors[5] <= 1;
            if (tx_push) begin tx_fifo[tx_wr] <= host_data; tx_wr <= tx_wr + 1'b1; end
            if (tx_pop) tx_rd <= tx_rd + 1'b1;
            case ({tx_push, tx_pop})
                2'b10: tx_used <= tx_used + 1'b1;
                2'b01: tx_used <= tx_used - 1'b1;
                default: begin end
            endcase
            if (rx_push) begin rx_fifo[rx_wr] <= rx_shift; rx_wr <= rx_wr + 1'b1; end
            if (rx_pop) rx_rd <= rx_rd + 1'b1;
            case ({rx_push, rx_pop})
                2'b10: rx_used <= rx_used + 1'b1;
                2'b01: rx_used <= rx_used - 1'b1;
                default: begin end
            endcase
            if (capture_push) begin
                capture_fifo[capture_wr] <= {timestamp, 3'b0, input_sync[4:0]};
                capture_wr <= capture_wr + 1'b1;
            end
            if (capture_pop) capture_rd <= capture_rd + 1'b1;
            case ({capture_push, capture_pop})
                2'b10: capture_used <= capture_used + 1'b1;
                2'b01: capture_used <= capture_used - 1'b1;
                default: begin end
            endcase
        end
    end

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
            stream_enabled <= 0;
            byte_count <= 0;
            capture_mask <= 0;
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
                stream_enabled <= 0;
                byte_count <= 0;
                capture_mask <= 0;
                running <= 0;
                halted <= 0;
                fault <= 0;
                pc <= 0;
                delay_left <= 0;
                out_enable <= 0;
            end else if (!run_prev) begin
                stream_enabled <= 0;
                byte_count <= 0;
                capture_mask <= 0;
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
                        4'hc: begin // Streaming and an independent byte-loop counter
                            case (instruction[27:24])
                                1: begin
                                    if (instruction[7:0] == 0) fail_closed();
                                    else begin
                                        stream_enabled <= 1;
                                        byte_count <= instruction[7:0];
                                        pc <= pc + 1'b1;
                                    end
                                end
                                2: begin // PULL stalls on empty; resets the bit loop/RX
                                    if (!stream_enabled) fail_closed();
                                    else if (tx_used != 0) begin
                                        tx_shift <= tx_fifo[tx_rd];
                                        loop_count <= 8;
                                        rx_shift <= 0;
                                        pc <= pc + 1'b1;
                                    end
                                end
                                3: begin // PUSH stalls on full without losing RX
                                    if (!stream_enabled) fail_closed();
                                    else if (rx_used < 8) pc <= pc + 1'b1;
                                end
                                4: begin
                                    if (!stream_enabled || byte_count == 0) fail_closed();
                                    else begin
                                        byte_count <= byte_count - 1'b1;
                                        pc <= byte_count == 1 ? pc + 1'b1 : {1'b0, instruction[5:0]};
                                    end
                                end
                                5: begin // Branch on final byte (I2C final NACK)
                                    if (!stream_enabled || byte_count == 0) fail_closed();
                                    else pc <= byte_count == 1 ? {1'b0, instruction[5:0]} : pc + 1'b1;
                                end
                                default: fail_closed();
                            endcase
                        end
                        4'hd: begin // Capture both edges of the selected synchronized lanes
                            if (!stream_enabled || instruction[27:24] != 1) fail_closed();
                            else begin
                                capture_mask <= instruction[4:0];
                                pc <= pc + 1'b1;
                            end
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
`ifdef FORMAL
`include "properties.vh"  // formal/properties.vh, staged by tools/formal.sh
`endif
endmodule
