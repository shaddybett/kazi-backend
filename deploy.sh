#!/bin/bash
# Exit immediately if a command exits with a non-zero status.
set -e

# Install dependencies
pip install -r requirements.txt

# Ensure the database is up to date
flask db upgrade

# Seed the database if necessary
if [ -f "seed.py" ]; then
  python seed.py
fi

# Start the application with gunicorn
exec gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 3
