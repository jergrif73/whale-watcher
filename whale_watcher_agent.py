name: Daily Market Report

on:
  schedule:
    - cron: '0 4,16 * * *' # Runs at 4 AM and 4 PM UTC
  workflow_dispatch: # Allows manual trigger

permissions:
  contents: write # Required to push changes

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: |
          pip install yfinance pandas lxml requests

      - name: Run Whale Watcher Agent
        env:
          SENDER_EMAIL: ${{ secrets.SENDER_EMAIL }}
          SENDER_PASSWORD: ${{ secrets.SENDER_PASSWORD }}
          RECEIVER_EMAIL: ${{ secrets.RECEIVER_EMAIL }}
          IS_MANUAL_RUN: ${{ github.event_name == 'workflow_dispatch' }}
        run: |
          python whale_watcher_agent.py

      - name: Commit and Push changes
        run: |
          git config --global user.name "GitHub Action"
          git config --global user.email "action@github.com"
          
          # Force add index.html (in case it's new)
          git add index.html
          
          # Check for changes and push if they exist
          if git diff --staged --quiet; then
            echo "No changes to commit."
          else
            git commit -m "Update Dashboard [skip ci]"
            # Explicitly push to the current branch to avoid Detached HEAD errors
            git push origin HEAD:${{ github.ref }}
          fi
