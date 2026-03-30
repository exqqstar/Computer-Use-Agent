"""Aggregate results.json and provenance.json files from sharded evaluation runs."""

import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Aggregate shard results and provenance into single output files")
    parser.add_argument("--num-shards", type=int, required=True)
    parser.add_argument("--shard-results-dir", default="shard-results")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    overall_sum = 0.0
    overall_count = 0
    per_domain: dict = {}
    participants = None

    image_digests = None
    _unset = object()
    github_actions = _unset
    shard_timestamps = []
    expected_dirs = [f"shard-{i}" for i in range(args.num_shards)]
    actual_dirs = os.listdir(args.shard_results_dir)
    if set(actual_dirs) != set(expected_dirs):
        print(f"Error: expected shard dirs {sorted(expected_dirs)}, got {sorted(actual_dirs)}")
        sys.exit(1)

    for shard_dir in expected_dirs:
        base = os.path.join(args.shard_results_dir, shard_dir)

        # Aggregate results
        with open(os.path.join(base, "results.json")) as f:
            data = json.load(f)
        shard_participants = data.get("participants", {})
        if participants is None:
            participants = shard_participants
        elif shard_participants != participants:
            print(f"Error: participants mismatch in {shard_dir}")
            print(f"  Expected: {participants}")
            print(f"  Got:      {shard_participants}")
            sys.exit(1)
        for result in data.get("results", []):
            o = result["overall"]
            overall_sum += o["sum"]
            overall_count += o["count"]
            for domain, d in result["per_domain"].items():
                if domain not in per_domain:
                    per_domain[domain] = {"sum": 0.0, "count": 0}
                per_domain[domain]["sum"] += d["sum"]
                per_domain[domain]["count"] += d["count"]

        # Merge provenance
        with open(os.path.join(base, "provenance.json")) as f:
            prov = json.load(f)

        shard_timestamps.append(prov.get("timestamp"))

        if image_digests is None:
            image_digests = prov.get("image_digests")
            if not image_digests:
                print(f"Error: missing image_digests in {shard_dir}")
                sys.exit(1)
        elif prov.get("image_digests") != image_digests:
            print(f"Error: image_digests mismatch in {shard_dir}")
            print(f"  Expected: {image_digests}")
            print(f"  Got:      {prov.get('image_digests')}")
            sys.exit(1)

        if github_actions is _unset:
            github_actions = prov.get("github_actions")
        elif prov.get("github_actions") != github_actions:
            print(f"Error: github_actions mismatch in {shard_dir}")
            print(f"  Expected: {github_actions}")
            print(f"  Got:      {prov.get('github_actions')}")
            sys.exit(1)

    success_rate = overall_sum / overall_count if overall_count else 0.0

    os.makedirs(args.output_dir, exist_ok=True)

    with open(os.path.join(args.output_dir, "results.json"), "w") as f:
        json.dump({
            "participants": participants,
            "results": [{
                "overall": {"sum": overall_sum, "count": overall_count},
                "success_rate": success_rate,
                "per_domain": per_domain,
            }],
        }, f, indent=2)
    print(f"success_rate={success_rate:.4f} over {overall_count} examples")

    provenance: dict = {
        "image_digests": image_digests,
        "shard_timestamps": shard_timestamps,
    }
    if github_actions and github_actions is not _unset:
        provenance["github_actions"] = github_actions
    with open(os.path.join(args.output_dir, "provenance.json"), "w") as f:
        json.dump(provenance, f, indent=2)
    print(f"Recorded provenance ({args.num_shards} shards)")


if __name__ == "__main__":
    main()
