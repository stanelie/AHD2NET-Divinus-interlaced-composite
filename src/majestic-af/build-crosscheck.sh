#!/bin/bash
CC="$HOME/arm-linux-musleabihf-cross/bin/arm-linux-musleabihf-gcc"
cd "$(dirname "$0")" || exit 1
SRCS="src/plugin.c src/motion.c src/proto.c src/engine.c src/af2.c src/af3.c src/actuator.c src/schema.c src/act_uart.c src/act_ms41908.c src/ms41908_calc.c src/act_gpiostep.c src/gpiostep_calc.c src/act_panasonic.c"
"$CC" -shared -fPIC -Os -std=gnu99 -Wall -Wextra -Iinclude -DFILE_BASENAME='"majestic-af"' $SRCS -lm -lpthread -o "$HOME/majestic-af.so"
echo "=== gcc exit $? ==="
ls -la "$HOME/majestic-af.so" 2>/dev/null && file "$HOME/majestic-af.so"
