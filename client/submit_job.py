import argparse
import json
import sys
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="http://127.0.0.1:8000")
    p.add_argument("--m", type=int, required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--k", type=int, required=True)
    p.add_argument("--dtype", choices=["fp16", "fp32"], default="fp32")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--simulate", action="store_true")
    args = p.parse_args()

    payload = {
        "spec": {
            "op": "gemm",
            "m": args.m,
            "n": args.n,
            "k": args.k,
            "dtype": args.dtype,
            "repeats": args.repeats,
            "seed": args.seed,
            "simulate": bool(args.simulate),
        }
    }

    body = json.dumps(payload).encode("utf-8")
    req = Request(args.host.rstrip("/") + "/v1/jobs", data=body, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    job_id = data["job_id"]
    print("job_id:", job_id)

    with urlopen(args.host.rstrip("/") + f"/v1/jobs/{job_id}") as resp:
        print("status:", json.loads(resp.read().decode("utf-8")))

    with urlopen(args.host.rstrip("/") + f"/v1/jobs/{job_id}/result") as resp:
        print("result:", json.loads(resp.read().decode("utf-8")))


if __name__ == "__main__":
    main()
