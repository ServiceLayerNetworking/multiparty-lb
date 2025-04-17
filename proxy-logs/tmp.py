import sys
import statistics

# Read microsecond values from stdin (e.g., piped from awk)
us_times = [int(line.strip()[:-2]) for line in sys.stdin if line.strip()[:-2].isdigit()]

# Basic stats
print(f"Count: {len(us_times)}")
print(f"Min: {min(us_times)} us")
print(f"Max: {max(us_times)} us")
print(f"Mean: {statistics.mean(us_times):.2f} us")
print(f"Median: {statistics.median(us_times)} us")
print(f"Std Dev: {statistics.stdev(us_times):.2f} us" if len(us_times) > 1 else "Std Dev: N/A")
