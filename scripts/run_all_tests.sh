#!/usr/bin/env bash
# Junior Aladdin — Run All Tests
# Usage: bash scripts/run_all_tests.sh
#
# Runs pytest with coverage reporting across all test directories.

set -e

echo "========================================"
echo " Junior Aladdin — Running All Tests"
echo "========================================"

# Ensure we're in project root
cd "$(dirname "$0")/.."

# Run pytest with options
python -m pytest tests/ \
    -v \
    --tb=short \
    --cov=junior_aladdin \
    --cov-report=term-missing \
    --cov-report=html:.coverage_html \
    2>&1

echo ""
echo "========================================"
echo " Tests complete."
echo " Coverage report: .coverage_html/index.html"
echo "========================================"
