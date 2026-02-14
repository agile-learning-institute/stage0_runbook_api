# LongRunningRunbook
A sample runbook that runs for a configurable duration and streams progress updates. Use this to test the streaming execution UI and verify that stdout flows in real time.

# Environment Requirements
```yaml
CYCLES: Number of 2-second cycles to run, e.g. 15 = ~30 seconds (default 15)
```

# File System Requirements
```yaml
Input:
```

# Required Claims
```yaml
roles: sre, api
```

# Script
```sh
#! /bin/zsh
echo "Cycles: $CYCLES"
echo "LongRunningRunbook starting (duration: ${CYCLES}s)"
echo "Streaming updates every 2 seconds..."
echo ""

for i in $(seq 1 $CYCLES); do
  echo "****************************************************************"
  echo "***** [$i/${CYCLES}] $(date -u +%H:%M:%S) - Still running..."
  echo "****************************************************************"
  sleep 2
done

echo ""
echo "LongRunningRunbook completed successfully"
```

# History
