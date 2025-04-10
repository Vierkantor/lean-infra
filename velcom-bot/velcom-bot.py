#!/usr/bin/env python3
#
# VelCom integration for Zulip
# Code inspired by `rss-bot`: RSS integration for Zulip

import argparse
import json
import re
import os
from typing import Any, Dict
import urllib.request

import zulip

DEFAULT_DATA_DIR = os.path.expanduser(os.path.join("~", ".cache", "velcom-bot"))  # type: str

# Maximum number of difference to include before truncating.
MAX_DIFFS = 5

usage = """Usage: Send summaries of VelCom benchmarks to Zulip.

To use this script:

1. Create a file containing 1 VelCom root URL per line (default location: ~/.cache/velcom-bot/api-urls)
Example URL: https://speed.lean-lang.org/lean4
2. Subscribe to the stream that will receive updates (default stream: rss)
3. Create a ~/.zuliprc as described on https://zulip.com/api/configuring-python-bindings
4. Test the script by running it manually, like this:

./velcom-bot.py

You can customize the location of the urls file and recipient stream, e.g.:

./velcom-bot.py --urls-file=/path/to/my/api-urls --stream=benchmarks

4. Configure a crontab entry for this script. A sample crontab entry for
running the bot every 5 minutes is:

*/5 * * * * /path/to/velcom-bot.py"""

parser = zulip.add_default_arguments(
    argparse.ArgumentParser(usage)
)
parser.add_argument(
    "--stream",
    dest="stream",
    help="The stream to which to send VelCom messages.",
    default="rss",
    action="store",
)
parser.add_argument(
    "--data-dir",
    dest="data_dir",
    help="The directory where metadata is stored",
    default=os.path.join(DEFAULT_DATA_DIR),
    action="store",
)
parser.add_argument(
    "--urls-file",
    dest="urls_file",
    help="The file containing a list of VelCom URLs to follow, one URL per line. Example URL: https://speed.lean-lang.org/lean4/api/recent/runs?n=10&significant=true",
    default=os.path.join(DEFAULT_DATA_DIR, "api-urls"),
    action="store",
)

opts = parser.parse_args()

os.makedirs(opts.data_dir, exist_ok=True)

# From rss-bot:
def elide_subject(subject: str) -> str:
    MAX_TOPIC_LENGTH = 60
    if len(subject) > MAX_TOPIC_LENGTH:
        subject = subject[: MAX_TOPIC_LENGTH - 3].rstrip() + "..."
    return subject

client = zulip.Client(
    email=opts.zulip_email,
    api_key=opts.zulip_api_key,
    config_file=opts.zulip_config_file,
    site=opts.zulip_site,
    client="VelcomBot/0.1",
)

with open(opts.urls_file) as f:
    urls = [url.strip() for url in f.readlines()]

def round_to_human_units(value) -> str:
    """Round a number to human-readable units such as kilo/mega/giga/..."""
    units = ["", "K", "M", "G", "T"]
    for unit in units:
        result = f"{value:.3g} {unit}"
        if abs(value) < 1000:
            return result
        value /= 1000
    return result

def format_difference(difference: Dict[str, Any]) -> str:
    benchmark = difference['dimension']['benchmark']
    interpretation = difference['dimension']['interpretation']
    metric = difference['dimension']['metric']
    unit = difference['dimension']['unit']
    absolute = difference['diff']
    relative = difference['reldiff']

    if interpretation == 'LESS_IS_BETTER':
        if absolute > 0:
            symbol = ':red_square: ▲'
        else:
            symbol = ':check: ▼'
    elif interpretation == 'MORE_IS_BETTER':
        if absolute < 0:
            symbol = ':red_square: :down:'
        else:
            symbol = ':check: :up:'
    else:
        # Unsure how to interpret. Draw a bullet.
        symbol = '•'

    percentage = relative * 100
    return f"| {symbol} | {benchmark} | {metric}: {round_to_human_units(absolute)} {unit} | {percentage:.3g} % |"

template = """**{commit_summary}**
[`{commit_hash}`]({repo_url}/commit/{commit_hash})
Author: {commit_author}

[Significant benchmark differences]({run_url}):

| | | | |
|--|--|--|--:|
{differences}
"""

truncated_template = """**{commit_summary}**
[`{commit_hash}`]({repo_url}/commit/{commit_hash})
Author: {commit_author}

[Significant benchmark differences]({run_url}):

| | | | |
|--|--|--|--:|
{differences}

[+ {truncated_count} more...]({run_url})
"""

for url in urls:
    hash_file = os.path.join(opts.data_dir, "processed-hashes")
    try:
        with open(hash_file) as f:
            processed_hashes = set(l.strip() for l in f)
    except OSError:
        processed_hashes = set()

    repo_data_url = url + "/api/all-repos"
    with urllib.request.urlopen(repo_data_url) as f:
        unparsed_repo_data = json.load(f)['repos']
    repo_data = {}
    for repo in unparsed_repo_data:
        repo_data[repo['id']] = repo

    significant_runs_url = url + "/api/recent/runs?n=10&significant=true"
    with urllib.request.urlopen(significant_runs_url) as f:
        runs_data = json.load(f)['runs']

    new_hashes = set()
    # Newer runs appear first in the API results but should be posted last,
    # so reverse the order.
    for run in reversed(runs_data):
        run_id = run['run']['id']
        # Only process new runs.
        if run_id in processed_hashes:
            continue
        new_hashes.add(run_id)

        run_url = url + "/run-detail/" + run_id

        try:
            commit_data = run['run']['source']['source']
        except KeyError:
            # Skip non-commit benchmarks.
            continue

        commit_hash = commit_data['hash']

        commit_author = commit_data['author']
        commit_summary = commit_data['summary'].strip()

        repo_id = commit_data['repo_id']
        repo_url = repo_data[repo_id]['remote_url']
        # We want the name as used in URLs, not the human-friendly display name.
        repo_name = repo_url.split('/')[-1]

        # Process the commit text so links lead to the right place.
        commit_summary = re.sub(r'(?<!\w)(#[0-9]+)\b', lambda m: repo_name + m.group(0), commit_summary)

        try:
            significant_differences = run['significant_differences']
        except KeyError:
            # Skip non-significant results.
            continue

        differences = "\n".join(format_difference(diff) for diff in significant_differences[:MAX_DIFFS])

        if len(significant_differences) > MAX_DIFFS:
            truncated_count = len(significant_differences) - MAX_DIFFS

            content = truncated_template.format(
                commit_hash=commit_hash,
                commit_author=commit_author,
                commit_summary=commit_summary,
                repo_url=repo_url,
                run_id=run_id,
                run_url=run_url,
                differences=differences,
                truncated_count=truncated_count
            )
        else:
            content = template.format(
                commit_hash=commit_hash,
                commit_author=commit_author,
                commit_summary=commit_summary,
                repo_url=repo_url,
                run_id=run_id,
                run_url=run_url,
                differences=differences,
                truncated_count=truncated_count
            )

        message = {
            "type": "stream",
            "sender": opts.zulip_email,
            "to": opts.stream,
            "subject": f"Benchmark results for {repo_name}",
            "content": content,
        }
        response = client.send_message(message)
        if response['result'] != 'success':
            print(f"Failed to send message: {response}")

    with open(hash_file, "a") as f:
        for hash in new_hashes:
            f.write(hash + "\n")
