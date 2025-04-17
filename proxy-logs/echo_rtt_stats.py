import sys
import subprocess
import statistics

if len(sys.argv) != 2:
    print("Usage: python3 stats.py <filename>")
    sys.exit(1)

filename = sys.argv[1]

# Run the awk command to extract microsecond values from the file
try:
    result = subprocess.run(
        ["awk", "/Round trip time from echo server:/ { print $15 }", filename],
        capture_output=True,
        text=True,
        check=True
    )
except subprocess.CalledProcessError as e:
    print(f"Error running awk: {e.stderr}")
    sys.exit(1)

# Parse and clean the output (remove 'us' and non-digit lines)
us_times = []
for line in result.stdout.splitlines():
    line = line.strip().replace("us", "")
    if line.isdigit():
        us_times.append(int(line))

# Check if we have data
if not us_times:
    print("No valid time entries found.")
    sys.exit(1)

# Stats
print(f"Count: {len(us_times)}")
print(f"Min: {min(us_times)} us")
print(f"Max: {max(us_times)} us")
print(f"Mean: {statistics.mean(us_times):.2f} us")
print(f"Median: {statistics.median(us_times)} us")
print(f"Std Dev: {statistics.stdev(us_times):.2f} us" if len(us_times) > 1 else "Std Dev: N/A")
