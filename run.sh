#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    /opt/homebrew/opt/python@3/bin/python3 -m venv .venv
fi

source .venv/bin/activate

if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "⚠️  Please update .env with your GROQ_API_KEY and GEMINI_API_KEY."
fi

echo "Starting Short Script Extractor API..."
python main.py
