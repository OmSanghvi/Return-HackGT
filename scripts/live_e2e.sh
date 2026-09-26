#!/usr/bin/env bash
# Live end-to-end: project -> upload -> selection (SAM 3.1) -> generate (Fast-SAM3D) -> assets.
# Usage: live_e2e.sh <image> <"name1,name2,..."> [user]   (one selection + one 3D job per name)
set -euo pipefail
API=http://100.63.32.83:8000
IMG="$1"; OBJ="$2"; U="${3:-demo-alice}"
H=(-H "X-SketchScape-Dev-User: $U")
j() { python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

P=$(curl -sf "${H[@]}" -H 'Content-Type: application/json' -d '{"name":"e2e live test"}' $API/v1/projects | j "d['project_id']")
echo "project $P"
UP=$(curl -sf "${H[@]}" -F "image=@$IMG" $API/v1/projects/$P/uploads | tee /dev/stderr | j "d['upload_id']")
echo "upload $UP"
BODY=$(OBJ="$OBJ" python3 -c "import os,json,time;n=[x.strip() for x in os.environ['OBJ'].split(',') if x.strip()];print(json.dumps({'selections':[{'selection_id':f'sel-{int(time.time())}-{i}','prompt':{'text':t},'memory_text':f'e2e memory for {t}'} for i,t in enumerate(n)]}))")
curl -sf "${H[@]}" -H 'Content-Type: application/json' -d "$BODY" $API/v1/projects/$P/uploads/$UP/selections; echo

wait_jobs() {
  for i in $(seq 1 ${1:-60}); do
    J=$(curl -sf "${H[@]}" "$API/v1/projects/$P/jobs")
    echo "$J" | python3 -c "import sys,json;d=json.load(sys.stdin);js=d.get('jobs',d) if isinstance(d,dict) else d;print(' | '.join(f\"{x.get('kind')}:{x.get('status')}\" for x in js))"
    echo "$J" | python3 -c "import sys,json;d=json.load(sys.stdin);js=d.get('jobs',d) if isinstance(d,dict) else d;sys.exit(0 if js and all(x.get('status') in ('complete','mask_review','failed') for x in js) else 1)" && return 0
    sleep 10
  done; return 1
}
wait_jobs 30
SEGMENTED=$(curl -sf "${H[@]}" $API/v1/projects/$P/uploads/$UP | tee /dev/stderr | j "json.dumps([s['selection_id'] for s in d['selections'] if s['status']=='segmented'])")
echo; echo "segmented: $SEGMENTED"
[ "$SEGMENTED" = "[]" ] && { echo "nothing segmented"; exit 1; }
curl -sf "${H[@]}" -H 'Content-Type: application/json' -d "{\"selection_ids\":$SEGMENTED}" $API/v1/projects/$P/uploads/$UP/generate >/dev/null
wait_jobs 120
curl -sf "${H[@]}" $API/v1/projects/$P/assets | j "'\\n'.join(f\"asset {a['asset_id'][:8]} {a['status']} {a.get('artifact_url')} {a.get('error') or ''}\" for a in d)"
echo "PROJECT=$P"
