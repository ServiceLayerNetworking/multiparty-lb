for i in {2..31}; do
  echo 1 | sudo tee /sys/devices/system/cpu/cpu$i/online
done