# TradingView Race Condition Test Suite

This directory contains a comprehensive test for the TradingView signal processor's race condition handling.

## Problem Statement

When TradingView sends signals for position transitions (e.g., closing a long position and immediately opening a short position), the signals can arrive within milliseconds of each other. This creates a race condition where:

1. Signals might be processed out of order
2. The "flat" signal (close position) might be skipped in favor of the newer position signal
3. This can lead to incorrect position states in the trading system

### Example Scenario
```
17:32:00.883979 - SHORT signal (-100/100)  // Opens short position
17:32:00.890186 - FLAT signal (0/100)      // Should close previous position first!
```

## Solution Implementation

### 1. Targeted Pattern Detection
The improved implementation specifically targets only the race condition pattern we care about:
- **Position → Flat** (wrong order - needs reordering)
- **Flat → Position** (correct order - timestamp adjustment only)

Other signal patterns are left untouched:
- Position → Position changes (no reordering)
- Signals more than 5 seconds apart (no intervention)
- Multiple unrelated signals within 5 seconds (no grouping)

### 2. Efficient Processing
- Only examines pairs of consecutive signals
- Only intervenes when the specific race condition pattern is detected
- Avoids unnecessary grouping or processing of unrelated signals

### 3. Signal Reordering Logic
When a position→flat pattern is detected within 5 seconds:
1. The signals are reordered to flat→position
2. Timestamps are adjusted to maintain the correct order
3. An audit trail records the adjustment

### 4. Timestamp Adjustment
To maintain chronological order after reordering:
- The first signal (after reordering) keeps its timestamp
- The second signal gets a 1ms adjustment
- This ensures downstream systems process them in the correct order

### 5. Enhanced Audit Trail
Each processed signal now includes detailed audit information:
```json
{
  "audit": {
    "original_timestamp": "2025-06-04T17:32:00.890186",
    "adjusted": true,
    "adjustment_reason": "position_transition_reorder"
  }
}
```

## Configuration

### Threshold Setting
The close timestamp threshold is set to 5 seconds to accommodate single-threaded strategies:
```python
CLOSE_THRESHOLD = timedelta(seconds=5)
```

This threshold only applies to the specific position transition patterns, not all signals.

## Test Suite

### Files

- `test_race_conditions.py` - Comprehensive test script that:
  - Creates test signal files with known race conditions in an isolated subdirectory
  - Processes them using the actual TradingViewProcessor
  - Analyzes production signal files (read-only) for race conditions
  - Demonstrates how the processor handles various scenarios

### Running the Test

From the project root directory:
```bash
python tests/tv_race_condition/test_race_conditions.py
```

Or from this directory:
```bash
python test_race_conditions.py
```

### What the Test Does

1. **Creates Test Signals** - Generates test signal files in `test_signals/` subdirectory with:
   - Out-of-order race conditions (position → flat)
   - Correct order but close timing (flat → position)
   - Normal signals with no race conditions
   - Direct position changes (long → short)

2. **Processes Test Signals** - Uses the actual TradingViewProcessor to:
   - Detect and reorder out-of-order signals
   - Adjust timestamps to maintain chronological order
   - Create audit trails for all adjustments

3. **Analyzes Production Signals** - Examines real signal files (read-only) to:
   - Identify potential race conditions
   - Report what adjustments would be made
   - Provide statistics on race condition occurrences

4. **Cleans Up** - Automatically removes test signal files after completion

### Test Isolation

All test signals are created in a `test_signals/` subdirectory within this test directory, ensuring complete isolation from production data. The test directory is automatically cleaned up after the test completes.

## Example Processing

### Scenario 1: Out-of-Order (Needs Reordering)
Input:
```
17:32:00.883979 - SHORT (-100/100)
17:32:00.890186 - FLAT (0/100)
```

Output:
```
17:32:00.883979 - FLAT (0/100)     // Reordered, keeps first timestamp
17:32:00.884979 - SHORT (-100/100) // Reordered, timestamp adjusted +1ms
```

### Scenario 2: Correct Order (No Reordering)
Input:
```
18:15:30.100000 - FLAT (0/100)
18:15:30.200000 - LONG (50/100)
```

Output:
```
18:15:30.100000 - FLAT (0/100)   // No change
18:15:30.101000 - LONG (50/100)  // Timestamp adjusted +1ms for safety
```

### Scenario 3: Unrelated Signals (No Intervention)
Input:
```
20:00:00.000000 - LONG (50/100)
20:00:01.000000 - SHORT (-50/100)
```

Output:
```
20:00:00.000000 - LONG (50/100)   // No change
20:00:01.000000 - SHORT (-50/100) // No change
```

## Benefits

1. **Targeted Approach**: Only affects the specific race condition, leaving other signal processing untouched
2. **Efficient**: O(n) processing with minimal overhead
3. **Clear Audit Trail**: Detailed tracking of what was adjusted and why
4. **Predictable**: Only intervenes in well-defined scenarios

## Edge Cases Handled

1. **Correct Order Preservation**: Flat→Position signals are kept in order (only timestamps adjusted)
2. **Position to Position Changes**: Direct position changes without flat are not reordered
3. **Distant Signals**: Signals more than 5 seconds apart are not considered related
4. **Multiple Transitions**: Each pair is evaluated independently

## Expected Behavior

The processor should:
- Reorder out-of-order signals (position → flat becomes flat → position)
- Adjust timestamps by 1ms increments to maintain order
- Leave normal signals and direct position changes untouched
- Provide a complete audit trail of all adjustments 