#!/usr/bin/env python3
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--reference", required=True)
    args = p.parse_args()
    print(f"[todo] build bwa-mem2/minimap2/samtools indexes for {args.profile}: {args.reference}")

if __name__ == "__main__":
    main()
