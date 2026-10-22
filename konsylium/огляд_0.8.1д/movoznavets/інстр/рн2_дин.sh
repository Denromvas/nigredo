#!/bin/sh
# Регулярка з повтором із аргументу: Атанор (без віддачі) і еталон
cd /root/ai-agents/Nigredo/konsylium/суд9_0.8/movoznavets || exit 1
E=/root/ai-agents/Nigredo/interpreter/ngr.py
for n in 4294967294 4294967295 4294967296 99999999999999999999; do
  echo "=== n=$n"
  ATHANOR_NO_FALLBACK=1 ngr рн2_повтор_дин.ngr "$n" --слід "сліди/рн2_дин_$n.А" 2>&1 | tail -2
  echo "   А код=$?"
  echo "-- Е"
  python3 "$E" рн2_повтор_дин.ngr "$n" --слід "сліди/рн2_дин_$n.Е" 2>&1 | tail -2
done
