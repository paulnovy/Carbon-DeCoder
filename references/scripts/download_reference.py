#!/usr/bin/env python3
import argparse

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--dest", default="/data/references")
    args = p.parse_args()
    print(f"[todo] download reference profile={args.profile} dest={args.dest}")

if __name__ == "__main__":
    main()
