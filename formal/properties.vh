// SPDX-License-Identifier: Apache-2.0
// Formal properties for protocol_engine, included at the end of the module
// body when FORMAL is defined (tools/formal.sh). Immediate assertions only.
//   S*: safety invariants     L*: bounded liveness     D*: FIFO data integrity
reg f_past_valid = 0, f_rst_prev = 0;
always @(posedge clk) begin f_past_valid <= 1; f_rst_prev <= rst_n; end
initial assume (!rst_n);

wire [3:0] f_opcode = instruction[31:28];
wire f_valid = f_past_valid && rst_n && f_rst_prev;
wire f_queues_cleared = !rst_n || !ena || !run || !run_prev;

always @(posedge clk) if (f_valid) begin
    // S1. Fail-closed: no output enable unless running; fault implies halted;
    //     running and halted are exclusive.
    assert (running || out_enable == 0);
    assert (!fault || halted);
    assert (!(running && halted));
    // S2. RUN low for two synchronized samples releases every lane.
    assert (run || run_prev || pins_oe == 0);
    // S3. Loader bounds: never more than 64 words; a full store has no partial word.
    assert (length <= 64);
    assert (length != 64 || byte_index == 0);
    // S4. Queue occupancy matches the pointers and never exceeds eight.
    assert (tx_used <= 8 && rx_used <= 8 && capture_used <= 8);
    assert (tx_used == 8 ? tx_wr == tx_rd : tx_used == ((tx_wr - tx_rd) & 3'h7));
    assert (rx_used == 8 ? rx_wr == rx_rd : rx_used == ((rx_wr - rx_rd) & 3'h7));
    assert (capture_used == 8 ? capture_wr == capture_rd
                              : capture_used == ((capture_wr - capture_rd) & 3'h7));
    // S5. Streaming instructions fault unless STREAM ran first.
    if ($past(issue && (f_opcode == 4'hc || f_opcode == 4'hd) &&
              !stream_enabled && instruction[27:24] != 1))
        assert (fault);
    // S6. A fault arises only from an executed instruction, a bad program at the
    //     RUN rising edge, or running off the end: host traffic cannot fault the engine.
    if (fault && !$past(fault))
        assert ($past(issue) || $past(ena && run && !run_prev) ||
                $past(running && delay_left == 0 && pc >= length));
    // S7. Bounded WAIT: while running, a nonzero elapsed count exists only at an
    //     issuable WAIT with a timeout and stays below it, so with L1 a WAIT completes
    //     or faults within timeout clocks. (An aborted RUN leaves the count until the
    //     next RUN rising edge clears it; the engine is not running then.)
    assert (wait_elapsed == 0 || !running ||
            (f_opcode == 4'h1 && delay_left == 0 && pc < length &&
             instruction[27:10] != 0 && wait_elapsed < instruction[27:10]));
    // L1. While stalled on a WAIT with a timeout, the counter advances every issue clock.
    if ($past(issue && f_opcode == 4'h1 && instruction[27:10] != 0 && instruction[2:0] <= 4) &&
        running && pc == $past(pc))
        assert (wait_elapsed == $past(wait_elapsed) + 1);
    // S8. DRIVE and PATCH delays are exact: delay_left counts down by one per clock.
    if ($past(running && delay_left != 0 && ena && run && run_prev) && running)
        assert (delay_left == $past(delay_left) - 1);
    // S9. Timestamp wrap while running is recorded as a sticky error.
    if ($past(running && timestamp == 24'hffffff && ena && run && run_prev))
        assert (host_errors[5]);
    // S10. A running program has no partial loader word, so the loader cannot
    //      write program memory on the clock RUN drops (writes need byte_index 3).
    assert (!running || byte_index == 0);
end

// D1. TX integrity: a pushed byte stays in its slot until the PULL that reaches
//     it loads exactly that byte. The tag picks one push nondeterministically.
reg f_tx_valid = 0;
reg [7:0] f_tx_value;
reg [2:0] f_tx_slot;
wire f_tx_pick = $anyseq;
always @(posedge clk) begin
    if (f_queues_cleared) f_tx_valid <= 0;
    else if (tx_push && !f_tx_valid && f_tx_pick) begin
        f_tx_valid <= 1;
        f_tx_value <= host_data;
        f_tx_slot <= tx_wr;
    end else if (tx_pop && f_tx_valid && tx_rd == f_tx_slot)
        f_tx_valid <= 0;
end
always @(posedge clk) if (f_valid) begin
    if (f_tx_valid) assert (((f_tx_slot - tx_rd) & 3'h7) < tx_used);  // slot is occupied
    if (f_tx_valid) assert (tx_fifo[f_tx_slot] == f_tx_value);
    if ($past(tx_pop && f_tx_valid && tx_rd == f_tx_slot && !f_queues_cleared))
        assert (tx_shift == $past(f_tx_value));
end

// D2. RX integrity: a pushed receive byte is what the host reads when its slot
//     becomes the head.
reg f_rx_valid = 0;
reg [7:0] f_rx_value;
reg [2:0] f_rx_slot;
wire f_rx_pick = $anyseq;
always @(posedge clk) begin
    if (f_queues_cleared) f_rx_valid <= 0;
    else if (rx_push && !f_rx_valid && f_rx_pick) begin
        f_rx_valid <= 1;
        f_rx_value <= rx_shift;
        f_rx_slot <= rx_wr;
    end else if (rx_pop && f_rx_valid && rx_rd == f_rx_slot)
        f_rx_valid <= 0;
end
always @(posedge clk) if (f_valid) begin
    if (f_rx_valid) assert (((f_rx_slot - rx_rd) & 3'h7) < rx_used);
    if (f_rx_valid) assert (rx_fifo[f_rx_slot] == f_rx_value);
    if (f_rx_valid && rx_rd == f_rx_slot && read_page == 4) assert (page_data == f_rx_value);
end

// D3. Capture integrity: an entry keeps its timestamp and pins until popped, and
//     is presented unchanged as the head.
reg f_cap_valid = 0;
reg [31:0] f_cap_value;
reg [2:0] f_cap_slot;
wire f_cap_pick = $anyseq;
always @(posedge clk) begin
    if (f_queues_cleared) f_cap_valid <= 0;
    else if (capture_push && !f_cap_valid && f_cap_pick) begin
        f_cap_valid <= 1;
        f_cap_value <= {timestamp, 3'b0, input_sync[4:0]};
        f_cap_slot <= capture_wr;
    end else if (capture_pop && f_cap_valid && capture_rd == f_cap_slot)
        f_cap_valid <= 0;
end
always @(posedge clk) if (f_valid) begin
    if (f_cap_valid) assert (((f_cap_slot - capture_rd) & 3'h7) < capture_used);
    if (f_cap_valid) assert (capture_fifo[f_cap_slot] == f_cap_value);
    if (f_cap_valid && capture_rd == f_cap_slot) assert (capture_head == f_cap_value);
end

// Reachability, so the checks above are not vacuous.
always @(posedge clk) if (f_valid) begin
    cover (tx_pop);
    cover (rx_pop);
    cover (capture_pop);
    cover (halted && !fault);
    cover (fault && $past(issue && f_opcode == 4'h1));
    cover (f_tx_valid && tx_used == 8);
end
