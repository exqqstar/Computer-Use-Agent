"""Patch scenario.toml with shard_index and num_shards for sharded evaluation runs."""

import argparse
import sys

try:
    import tomllib as tomli
except ImportError:
    import tomli
import tomli_w


def main():
    parser = argparse.ArgumentParser(description="Patch scenario.toml with shard config")
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--num-shards", type=int, required=True)
    parser.add_argument("--scenario", default="scenario.toml")
    args = parser.parse_args()

    with open(args.scenario, "rb") as f:
        data = tomli.load(f)
    data.setdefault("config", {})["shard_index"] = args.shard_index
    data["config"]["num_shards"] = args.num_shards
    with open(args.scenario, "wb") as f:
        tomli_w.dump(data, f)
    print(f"Patched {args.scenario}: shard_index={args.shard_index}, num_shards={args.num_shards}")


if __name__ == "__main__":
    main()
