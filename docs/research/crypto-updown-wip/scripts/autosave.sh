#!/bin/bash
# Sauvegarde automatique toutes les 5 min vers origin/research/crypto-updown (3 h max)
S=/tmp/claude-0/-home-user-polycopy/c1517565-1179-5cad-9d67-6c943a23d73d/scratchpad; WT=$S/wt; D=$WT/docs/research/crypto-updown-wip
END=$(( $(date +%s) + 10800 ))
while [ $(date +%s) -lt $END ]; do
  mkdir -p $D/scripts $D/outputs
  cp $S/scripts/*.py $S/scripts/*.sh $D/scripts/ 2>/dev/null
  cp $S/phase*.md $S/out_*.txt $S/live/collector.log $D/outputs/ 2>/dev/null
  [ -f $S/../crypto-updown-feasibility.md ] && true
  [ -f $S/report/crypto-updown-feasibility.md ] && cp $S/report/crypto-updown-feasibility.md $WT/docs/research/ 2>/dev/null
  [ -d $S/report/img ] && mkdir -p $WT/docs/research/img && cp $S/report/img/*.png $WT/docs/research/img/ 2>/dev/null
  cd $WT
  if [ -n "$(git status --porcelain docs/research)" ]; then
    git add docs/research && git commit -q -m "docs(research): autosave WIP $(date -u +%H:%M)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01YBX2PC5KGkVUajHXV7rMam"
    for i in 1 2 3 4; do git push -q origin research/crypto-updown && break || sleep $((2**i)); done
    echo "$(date -u +%H:%M:%S) pushed"
  else echo "$(date -u +%H:%M:%S) nothing"; fi
  sleep 300
done
