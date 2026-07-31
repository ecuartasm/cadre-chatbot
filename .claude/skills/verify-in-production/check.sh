#!/usr/bin/env bash
# Verify the DEPLOYED bot, not a local one.
#
# Six defects in this build were found only here: the missing COPY content/, the volume mount path,
# the request-id plumbing, the rate limiter's bucketing, the woff2 mimetype, and a price anchor the
# eval had passed locally minutes before. Local green is weaker evidence than it feels.
#
# Usage:  ./check.sh [--wait] [--url URL]
#   --wait   poll until the service is healthy first (use right after `railway up`)

set -uo pipefail
URL="https://cadre-chatbot-production.up.railway.app"
WAIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --wait) WAIT=1 ;;
    --url) shift; URL="$1" ;;
  esac
  shift
done

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$1" 2>/dev/null; }
jqp()  { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)" 2>/dev/null; }

if [ "$WAIT" = 1 ]; then
  # A deploy takes minutes and a 502 mid-swap is normal, not a failure. `railway up` printing
  # "Failed to stream build logs" also does NOT mean the deploy failed — it means the log stream
  # dropped. Check the service, and `railway deployment list` for DEPLOYING vs SUCCESS.
  echo "waiting for $URL to become healthy..."
  for _ in $(seq 1 60); do
    [ "$(code "$URL/health")" = "200" ] && break
    sleep 10
  done
fi

S=$(code "$URL/health")
if [ "$S" != "200" ]; then
  echo "UNHEALTHY: /health returned $S"
  echo "Check \`railway deployment list\` — DEPLOYING means still building, not broken."
  exit 1
fi

HEALTH=$(curl -s --max-time 20 "$URL/health")
CONFIG=$(curl -s --max-time 20 "$URL/api/config")
STATS=$(curl -s --max-time 20 "$URL/api/stats")

echo "=== identity — does the deployed thing match the repo? ==="
printf '  prompt version : %s\n' "$(printf '%s' "$CONFIG" | jqp "d['system_prompt_version']")"
printf '  corpus sha     : %s   (compare: git-tracked corpus)\n' \
  "$(printf '%s' "$CONFIG" | jqp "d['corpus']['sha256']")"
printf '  model          : %s\n' "$(printf '%s' "$HEALTH" | jqp "d['model']")"

echo
echo "=== the log sink must be writable or every number below is stale ==="
printf '  %s\n' "$(printf '%s' "$HEALTH" | jqp "'%s / writable=%s / retention %sd' % (d['log_sink']['mode'], d['log_sink']['writable'], d['log_sink']['retention_days'])")"

echo
echo "=== spend against the cap ==="
printf '  %s\n' "$(printf '%s' "$HEALTH" | jqp "'\$%.6f of \$%.2f (%.2f%%) on %s, %d turns' % (d['spend']['spend_today_usd'], d['spend']['cap_usd'], d['spend']['pct_of_cap'], d['spend']['date'], d['spend']['turns_today'])")"

echo
echo "=== behaviour ==="
AVAIL=$(printf '%s' "$STATS" | jqp "d.get('available')")
if [ "$AVAIL" = "True" ]; then
  printf '  %s\n' "$(printf '%s' "$STATS" | jqp "'%d turns, %.1f%% refused, cache hit %.1f%%, p50 %sms' % (d['turns'], d['refusal_rate'], d['cache']['hit_rate'], d['latency_ms']['p50'])")"
  printf '  refusals: %s\n' "$(printf '%s' "$STATS" | jqp "d['refusals_by_reason']")"
else
  printf '  /api/stats unavailable: %s\n' "$(printf '%s' "$STATS" | jqp "d.get('reason')")"
  echo "  (that is an honest 'cannot tell', not 'no traffic')"
fi

echo
echo "Next: run the golden set. It is the only check that proves BEHAVIOUR, and it has caught a"
echo "defect that passed locally minutes earlier."
echo "  python eval/golden.py --url $URL"
