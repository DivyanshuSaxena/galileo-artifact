#sudo -s, then run this script
sudo apt install -y cpufrequtils
killall cstate
gcc cstate.c -o cstate
./cstate 0 &
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
echo 1 | tee /sys/devices/system/cpu/intel_pstate/no_turbo
echo 1900000 | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq
echo 1900000 | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq
# watch -n 1 "cat /proc/cpuinfo | grep 'MHz'"
