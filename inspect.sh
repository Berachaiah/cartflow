#!/usr/bin/env bash
cd "$(dirname "$0")"
EX=( -not -path "*/venv/*" -not -path "*/node_modules/*" -not -path "*/__pycache__/*" -not -path "*/.git/*" )

echo "===== 1. STRUCTURE (depth 3) ====="
find . -maxdepth 3 "${EX[@]}" -not -name "*.pyc" -not -name ".DS_Store" | sort

echo; echo "===== 2. FILE TYPES ====="
find . -type f "${EX[@]}" | sed -E 's/.*\.([A-Za-z0-9]+)$/\1/' | sort | uniq -c | sort -rn | head -12

echo; echo "===== 3. PYTHON LINES BY FILE (top 20) ====="
find app -name "*.py" "${EX[@]}" -print0 | xargs -0 wc -l | sort -rn | head -21

echo; echo "===== 4. ROUTES ====="
grep -rnE "@(router|app)\.(get|post|put|patch|delete|websocket)\(" app --include="*.py" | sed -E 's/^([^:]+):([0-9]+):\s*/\1:\2  /'

echo; echo "===== 5. ROUTERS MOUNTED ====="
grep -rnE "include_router|APIRouter\(" app --include="*.py"

echo; echo "===== 6. MODELS / TABLES ====="
grep -rnE "^class .*\(.*(Base|Model|DeclarativeBase|TimestampMixin).*\)|__tablename__" app --include="*.py"

echo; echo "===== 7. MIGRATIONS ====="
ls app/database/migrations/versions
python -m alembic current 2>/dev/null | tail -1

echo; echo "===== 8. TEMPLATES & STATIC ====="
ls app/templates
echo "--- static ---"; find app/static -type f | sed 's|/[^/]*$||' | sort | uniq -c

echo; echo "===== 9. SETTINGS (names only, no values) ====="
grep -nE "^\s+[A-Z][A-Z0-9_]+\s*:" app/core/config.py
echo "--- keys defined in .env ---"; sed -E 's/=.*//' .env | grep -vE "^\s*(#|$)"

echo; echo "===== 10. DEPENDENCIES ====="
cat requirements.txt
echo "--- npm scripts ---"; grep -A8 '"scripts"' package.json

echo; echo "===== 11. TESTS ====="
find tests -name "*.py" | wc -l
python -m pytest --collect-only -q 2>/dev/null | tail -3

echo; echo "===== 12. TODO / FIXME ====="
grep -rnE "TODO|FIXME|HACK|XXX" app --include="*.py" --include="*.html" --include="*.js" | head -30

echo; echo "===== 13. SECURITY CHECKS ====="
echo "--- .gitignore covers env? ---"; grep -nE "^\.env|^venv|node_modules" .gitignore 2>/dev/null || echo "NO .gitignore entries found"
echo "--- stray secret-looking files ---"; ls -a | grep -E "cookies|\.env\.|\.bak|\.zip"
echo "--- hardcoded secrets in code ---"
grep -rnEi "(secret|password|api_key|token)\s*=\s*['\"][^'\"]{6,}" app --include="*.py" | grep -viE "example|placeholder|changeme|test" | head

echo; echo "===== 14. GIT ====="
git status -s 2>/dev/null | head -20
git log --oneline -5 2>/dev/null
