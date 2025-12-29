from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_submit_and_get_simulated_job():
    r = client.post("/v1/jobs", json={"spec": {"op": "gemm", "m": 4096, "n": 4096, "k": 4096, "dtype": "fp16", "repeats": 1, "seed": 1, "simulate": True}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    s = client.get(f"/v1/jobs/{job_id}")
    assert s.status_code == 200
    assert s.json()["state"] in ("DONE", "FAILED")

    out = client.get(f"/v1/jobs/{job_id}/result")
    assert out.status_code == 200
    js = out.json()
    assert js["job_id"] == job_id
    assert js["state"] in ("DONE", "FAILED")
    if js["state"] == "DONE":
        assert "checksum" in js["result_summary"]


def test_small_cpu_job():
    r = client.post("/v1/jobs", json={"spec": {"op": "gemm", "m": 16, "n": 16, "k": 16, "dtype": "fp32", "repeats": 2, "seed": 7, "simulate": False}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    out = client.get(f"/v1/jobs/{job_id}/result")
    assert out.status_code == 200
    js = out.json()
    assert js["state"] == "DONE"
    assert js["result_summary"]["mode"] == "cpu_gemm"
