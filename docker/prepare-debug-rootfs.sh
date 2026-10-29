#!/bin/sh
set -eu

# Run only in the frozen language-runtime build stage, before application jars,
# IDE management dependencies or operator configuration can enter the image.
destination=/prepared-debug-rootfs
test ! -e "$destination"
mkdir -m 0755 "$destination"
for name in bin sbin usr lib etc opt; do
    test -d "/$name"
    cp -a "/$name" "$destination/$name"
done
for name in lib32 lib64; do
    if [ -e "/$name" ] || [ -L "/$name" ]; then
        cp -a "/$name" "$destination/$name"
    fi
done
mkdir -p "$destination/work" "$destination/tmp" "$destination/proc" \
    "$destination/dev/pts" "$destination/sys/fs/cgroup" \
    "$destination/compile-cgroup" "$destination/control" "$destination/artifacts"
